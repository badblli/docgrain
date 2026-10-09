"""WP106 in the worker image: real Docling reads the synthetic samples of the new file types."""

from __future__ import annotations

import hashlib
import importlib.util
from datetime import UTC, datetime

import pytest
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import (
    processing_revision_id,
    source_revision_id,
)
from docgrain_domain.docling_formats import DOCLING_INPUT_FORMATS, NOT_ENABLED_MESSAGE
from docgrain_domain.source_format import (
    SourceFormat,
    declared_format,
    mime_for_filename,
    resolve_format,
    storage_suffix,
    verify_format,
)

from tests.fixtures import wp106_samples as samples

pytestmark = pytest.mark.skipif(importlib.util.find_spec("docling") is None,
                                reason="real Docling integration requires worker image")


def test_domain_snapshot_equals_installed_docling():
    from docgrain_worker.format_capabilities import live_snapshot, snapshot_matches

    assert live_snapshot() == DOCLING_INPUT_FORMATS
    assert snapshot_matches()


def stored(tmp_path, name, data):
    source_format = declared_format(name, mime_for_filename(name))
    verify_format(data, source_format)
    path = tmp_path / f"source.{storage_suffix(name, source_format)}"
    path.write_bytes(data)
    return path, source_format


@pytest.mark.parametrize("name", sorted(samples.SAMPLES))
def test_docling_detects_the_format_we_resolved(tmp_path, name):
    from docling.datamodel.document import _DocumentConversionInput

    data = samples.SAMPLES[name]()
    path, source_format = stored(tmp_path, name, data)
    resolved = resolve_format(data, source_format)
    detected = _DocumentConversionInput(path_or_stream_iterator=[])._guess_format(path)
    assert detected is not None
    assert detected.value == ("image" if resolved.value in {"tiff", "webp", "bmp"} else resolved.value)


def parse(tmp_path, name):
    from docgrain_worker.structural import DocumentParser, VerifiedSource

    data = samples.SAMPLES[name]()
    path, source_format = stored(tmp_path, name, data)
    result = DocumentParser().parse(VerifiedSource(path, hashlib.sha256(data).hexdigest(), len(data)), source_format)
    return result, data


@pytest.mark.parametrize("name", ["rooms.pptx", "rooms.html", "rooms.md", "rooms.csv", "rooms.eml", "rooms.epub",
                                  "rooms.vtt", "rooms.xml"])
def test_simple_formats_are_read_by_docling(tmp_path, name):
    result, _ = parse(tmp_path, name)
    assert result.status == "complete", [issue.reason for issue in result.issues]
    assert result.parser == "docling" and result.parser_version == "2.130.0"
    assert result.expected_areas == result.processed_areas == ["document"]
    text = " ".join(item.text for item in result.items) + " ".join(
        str(cell.get("value", "")) for item in result.items for row in item.cells for cell in row)
    assert "Garden" in text
    assert all(item.locator and item.locator["kind"] == "docx_raw" for item in result.items)


@pytest.mark.parametrize("name", ["rooms.tiff", "rooms.webp", "rooms.bmp"])
def test_image_types_use_full_page_ocr_and_keep_original_pixels(tmp_path, name):
    result, data = parse(tmp_path, name)
    assert result.status in {"complete", "partial"}
    assert result.source_format.value == name.rsplit(".", 1)[1]
    lines = [item for item in result.items if item.kind != "picture"]
    assert any("Garden" in item.text for item in lines)
    assert all(item.locator["kind"] == "image_region" for item in lines)
    original = next(item for item in result.items if item.anchor == "original-image")
    assert original.asset_bytes == data
    if name == "rooms.tiff":
        assert result.expected_areas == ["frame:1", "frame:2"]
        assert {item.text.split()[1] for item in lines if item.text.startswith("Page")} == {"1", "2"}
        assert lines[-1].locator["bbox"]["y"] > 0.5


def test_odt_needs_odfdo(tmp_path):
    result, _ = parse(tmp_path, "rooms.odt")
    if importlib.util.find_spec("odfdo") is None:
        assert result.status == "failed" and result.issues[0].code == "format_not_enabled"
        assert result.issues[0].reason.startswith(NOT_ENABLED_MESSAGE)
    else:
        assert result.status == "complete" and any("Garden" in item.text for item in result.items)


def test_audio_is_not_enabled_before_any_docling_call(tmp_path):
    from docgrain_worker.structural import DocumentParser, VerifiedSource

    data = samples.wav()
    path = tmp_path / "source.wav"
    path.write_bytes(data)
    result = DocumentParser().parse(VerifiedSource(path, hashlib.sha256(data).hexdigest(), len(data)), SourceFormat.AUDIO)
    assert result.status == "failed" and result.issues[0].code == "format_not_enabled"


@pytest.mark.parametrize("name", ["rooms.html", "rooms.tiff"])
def test_new_formats_map_to_canonical_snapshots(tmp_path, name):
    from docgrain_worker.canonical_mapper import CanonicalMapper
    from docgrain_worker.canonical_writer import processing_spec

    result, data = parse(tmp_path, name)
    digest = hashlib.sha256(data).hexdigest()
    source_id = source_revision_id("ws", "doc_1", digest)
    source = SourceVersion(id=source_id, document_id="doc_1", workspace_id="ws", content_sha256=digest,
                           storage_uri="s3://bucket/key?versionId=1", storage_version="1", byte_size=len(data),
                           mime_type=mime_for_filename(name), filename=name, recorded_at=datetime.now(UTC))
    for item in result.items:
        if item.kind == "picture" and item.asset_bytes:
            item.asset_path = "assets/original"
    spec = processing_spec(result)
    snapshot = CanonicalMapper().map(result, source, revision_id=processing_revision_id(source_id, spec),
                                     created_at=datetime.now(UTC), processing=spec)
    kinds = {evidence.locator.kind for evidence in snapshot.evidence}
    assert kinds == ({"image_region"} if name == "rooms.tiff" else {"artifact_object"})
