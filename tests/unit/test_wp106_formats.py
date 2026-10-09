"""WP106: every file type Docling reads, derived from one list; closed ones refused up front."""

from __future__ import annotations

import io
import json
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from docgrain_api import format_capabilities
from docgrain_api.main import app
from docgrain_api.routers import documents
from docgrain_domain.docling_formats import (
    DOCLING_INPUT_FORMATS,
    NOT_ENABLED_MESSAGE,
    SPECS,
    accepted_extensions,
    typescript_module,
)
from docgrain_domain.source_format import (
    MIME_TYPES,
    CorruptSource,
    FormatMismatch,
    FormatNotEnabled,
    SourceFormat,
    declared_format,
    ensure_enabled,
    format_for_filename,
    mime_for_filename,
    resolve_format,
    storage_suffix,
    verify_format,
)
from docgrain_ingest.cli import ingest_folder
from docgrain_worker import docling_dispatch
from docgrain_worker.image_formats import parse_image
from docgrain_worker.structural import (
    DocumentParser,
    StructuralItem,
    StructuralParseResult,
    VerifiedSource,
)
from fastapi.testclient import TestClient
from PIL import Image

from tests.fixtures import wp106_samples as samples

ROOT = Path(__file__).resolve().parents[2]


def test_original_six_values_and_mime_rules_are_unchanged():
    assert [f.value for f in list(SourceFormat)[:6]] == ["pdf", "docx", "txt", "xlsx", "png", "jpeg"]
    assert MIME_TYPES[SourceFormat.JPEG] == "image/jpeg" and len(MIME_TYPES) == 6
    assert declared_format("a.JPG", "image/jpeg") is SourceFormat.JPEG
    assert declared_format("a.txt", "text/plain") is SourceFormat.TXT
    for name, mime in [("a.png", "image/jpeg"), ("a.docx", "application/pdf"), ("a.txt", "text/markdown")]:
        with pytest.raises(FormatMismatch):
            declared_format(name, mime)
    assert storage_suffix("photo.jpg", SourceFormat.JPEG) == "jpeg"


def test_every_docling_extension_is_accepted_and_derived_from_the_snapshot():
    for name, (extensions, _) in DOCLING_INPUT_FORMATS.items():
        for extension in extensions:
            source_format = format_for_filename(f"file.{extension}")
            # TXT keeps Docgrain's exact text reader; a plain ".xml" is resolved from its content.
            expected = {"txt": "txt", "text": "txt", "xml": "xml"}.get(extension.lower())
            if expected:
                assert source_format.value == expected
            elif name == "image":
                assert SPECS[source_format.value].docling_format == "image"
            else:
                assert source_format.value == name, (name, extension)
    assert len(SourceFormat) == len(SPECS) and len(DOCLING_INPUT_FORMATS) == 34  # the WP text says 33; Docling 2.130 lists 34
    assert {spec.docling_format for spec in SPECS.values()} - {None} == set(DOCLING_INPUT_FORMATS)
    for extension in accepted_extensions():
        declared_format(f"file.{extension}", mime_for_filename(f"file.{extension}"))
    with pytest.raises(FormatMismatch):
        format_for_filename("tool.exe")
    assert format_for_filename("scan.dclg.xml") is SourceFormat.XML_DOCLANG
    assert format_for_filename("book.tar.gz") is SourceFormat.METS_GBS
    assert storage_suffix("mail.MSG", SourceFormat.EMAIL) == "msg"


def test_web_list_is_generated_from_the_same_module():
    generated = (ROOT / "apps/web/lib/source-formats.ts").read_text(encoding="utf-8")
    assert generated == typescript_module()
    assert ".ebc" not in generated and ".pptx" in generated and ".tiff" in generated


@pytest.mark.parametrize("name", sorted(samples.SAMPLES))
def test_synthetic_samples_pass_content_sniffing(name):
    data = samples.SAMPLES[name]()
    source_format = declared_format(name, mime_for_filename(name))
    verify_format(data, source_format)
    assert resolve_format(data, source_format).value == {"rooms.xml": "xml_jats"}.get(name, source_format.value)


@pytest.mark.parametrize(("name", "content"), [
    ("renamed.odt", samples.pptx), ("renamed.pptx", samples.odt), ("renamed.epub", samples.odt),
    ("renamed.vtt", samples.html), ("renamed.html", samples.vtt), ("renamed.eml", lambda: b"\x00binary"),
    ("renamed.webp", lambda: samples.image("PNG")), ("renamed.bmp", lambda: samples.image("WEBP")),
    ("renamed.tiff", lambda: samples.image("BMP")), ("renamed.xml", lambda: b"<note>plain xml</note>"),
    ("renamed.nxml", samples.xbrl), ("renamed.json", lambda: b'{"name": "not docling"}'),
    ("renamed.doc", lambda: b"PK\x03\x04 not ole"), ("renamed.wav", samples.vtt), ("renamed.rtf", samples.html),
])
def test_renamed_files_are_rejected_as_today(name, content):
    with pytest.raises((FormatMismatch, CorruptSource)):
        verify_format(content(), declared_format(name, "application/octet-stream"))


def test_animated_webp_and_closed_formats():
    frames = [Image.new("RGB", (8, 8), color) for color in ("white", "black")]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="WEBP", save_all=True, append_images=frames[1:])
    with pytest.raises(FormatMismatch):
        verify_format(buffer.getvalue(), SourceFormat.WEBP)
    verify_format(samples.legacy_doc(), SourceFormat.DOC)
    with pytest.raises(FormatNotEnabled) as closed:
        ensure_enabled(SourceFormat.DOC, {})
    assert str(closed.value) == NOT_ENABLED_MESSAGE and closed.value.missing == ("libreoffice",)
    ensure_enabled(SourceFormat.DOC, {"libreoffice": True})
    with pytest.raises(FormatNotEnabled):  # a copybook per file is never available
        ensure_enabled(SourceFormat.EBCDIC, {"ebcdic-layout": True})
    ensure_enabled(SourceFormat.PPTX, {})


@pytest.fixture
def api(monkeypatch, live_repository):
    stored, queued, report = {}, [], {"available": {}}
    monkeypatch.setattr(documents, "put_upload", lambda key, stream, mime, length: stored.update({key: stream.read()}))
    monkeypatch.setattr(documents, "object_exists", lambda key: key in stored)
    monkeypatch.setattr(documents, "enqueue", queued.append)
    monkeypatch.setattr(format_capabilities, "worker_report", lambda: report)
    return TestClient(app), stored, queued, report


def register(client, name, data, mime=None):
    return client.post("/v1/documents", json={
        "workspace_id": "ws_alpha", "filename": name, "mime_type": mime or mime_for_filename(name),
        "byte_size": len(data), "content_sha256": sha256(data).hexdigest()})


def test_api_accepts_base_formats_and_refuses_closed_ones_up_front(api):
    client, _, queued, report = api
    for name in ("rooms.pptx", "rooms.html", "rooms.md", "rooms.csv", "rooms.eml", "rooms.epub", "rooms.tiff",
                 "rooms.webp", "rooms.vtt"):
        data = samples.SAMPLES[name]()
        registration = register(client, name, data)
        assert registration.status_code == 202, name
        body = registration.json()
        assert client.put(body["upload_url"], files={"file": (name, data, mime_for_filename(name))}).status_code == 201
        assert client.post(f"/v1/documents/{body['document']['id']}/versions/{body['version']['id']}/uploaded").status_code == 202
    for name, data in [("rooms.odt", samples.odt()), ("rooms.wav", samples.wav()), ("old.doc", samples.legacy_doc())]:
        refused = register(client, name, data)
        assert refused.status_code == 415 and refused.json()["detail"] == NOT_ENABLED_MESSAGE
    assert len(queued) == 9
    report["available"] = {"odfdo": True}
    assert register(client, "rooms.odt", samples.odt()).status_code == 202
    formats = {item["format"]: item for item in client.get("/v1/formats").json()["formats"]}
    assert formats["odt"]["enabled"] and not formats["xls"]["enabled"] and formats["xls"]["missing"] == ["libreoffice"]
    assert formats["pptx"]["enabled"] and formats["pdf"]["extensions"] == ["pdf"]


def test_xml_type_is_decided_from_content_before_storage(api):
    client, stored, _, _ = api
    for name, data, status in [("rooms.xml", samples.jats(), 201), ("filing.xml", samples.xbrl(), 415)]:
        body = register(client, name, data).json()
        upload = client.put(body["upload_url"], files={"file": (name, data, "application/xml")})
        assert upload.status_code == status
    assert len(stored) == 1
    assert upload.json()["detail"] == NOT_ENABLED_MESSAGE


def test_ingest_folder_skips_nothing_docling_reads_and_reports_closed_types(tmp_path, api):
    client, _, queued, _ = api
    folder = tmp_path / "company"
    folder.mkdir()
    for name in ("rooms.pptx", "rooms.md", "rooms.csv", "rooms.vtt"):
        (folder / name).write_bytes(samples.SAMPLES[name]())
    (folder / "old.doc").write_bytes(samples.legacy_doc())
    (folder / "call.wav").write_bytes(samples.wav())
    (folder / "tool.exe").write_bytes(b"MZ")
    with httpx.Client(base_url="http://fake-api", transport=httpx.MockTransport(
            lambda request: _forward(client, request))) as http:
        report = ingest_folder(folder, "ws_alpha", http, report_path=tmp_path / "report.json", poll_interval=0,
                               timeout=0.001)
    rows = {row["file"]: row for row in report["files"]}
    assert all(rows[name]["document_id"] for name in ("rooms.pptx", "rooms.md", "rooms.csv", "rooms.vtt"))
    for name in ("old.doc", "call.wav"):
        assert rows[name]["status"] == "skipped" and rows[name]["issues"] == [{"reason": NOT_ENABLED_MESSAGE}]
    assert rows["tool.exe"]["issues"] == [{"reason": "Desteklenmeyen dosya türü."}]
    assert len(queued) == 4


def _forward(client, request):
    response = client.request(request.method, str(request.url), content=request.content, headers=dict(request.headers))
    return httpx.Response(response.status_code, content=response.content, headers=response.headers, request=request)


def test_worker_refuses_a_closed_format_with_the_turkish_reason(tmp_path, monkeypatch):
    from docgrain_worker import format_capabilities as worker_capabilities

    monkeypatch.setattr(worker_capabilities, "cached_probe", lambda: {"ffmpeg": True})
    path = tmp_path / "source.wav"
    path.write_bytes(samples.wav())
    data = path.read_bytes()
    result = DocumentParser().parse(VerifiedSource(path, sha256(data).hexdigest(), len(data)), SourceFormat.AUDIO)
    assert result.status == "failed" and result.issues[0].code == "format_not_enabled"
    assert result.issues[0].reason.startswith(NOT_ENABLED_MESSAGE) and "asr-profile" in result.issues[0].reason
    assert docling_dispatch.closed_format_result(SourceFormat.PPTX) is None


def _fake_png_read(prepared: bytes, metadata: dict) -> StructuralParseResult:
    """Stands in for the PNG Docling route: one text line in the middle of every page."""
    from docgrain_worker.image_geometry import image_locator

    width, height = metadata["input_width_px"], metadata["input_height_px"]
    box = {"l": 0.1 * width, "t": 0.4 * height, "r": 0.9 * width, "b": 0.6 * height, "coord_origin": "TOPLEFT"}
    line = StructuralItem("paragraph", "#/texts/0", image_locator(box, (width, height), metadata), text="Garden")
    whole = {"kind": "image_region", "width_px": metadata["width_px"], "height_px": metadata["height_px"],
             "exif_orientation": metadata["exif_orientation"], "bbox": {"x": 0, "y": 0, "width": 1, "height": 1}}
    original = StructuralItem("picture", "original-image", whole, asset_bytes=prepared, asset_mime="image/png")
    return StructuralParseResult(SourceFormat.PNG, "docling", "2.130.0", "complete", [line, original], ["image"],
                                 ["image"], [], {"ocr_cells": [{"text": "Garden", "locator": line.locator}]},
                                 {"pipeline": {}}, legacy_markdown=b"Garden")


def test_multi_page_tiff_keeps_exact_page_coordinates():
    data = samples.tiff(pages=2)
    result = parse_image(data, SourceFormat.TIFF, _fake_png_read)
    assert result.source_format is SourceFormat.TIFF and result.expected_areas == ["frame:1", "frame:2"]
    lines = [item for item in result.items if item.kind == "paragraph"]
    assert [item.anchor for item in lines] == ["frame:1:#/texts/0", "frame:2:#/texts/0"]
    first, second = (item.locator for item in lines)
    assert (first["width_px"], first["height_px"]) == (900, 600)
    assert first["bbox"]["y"] == pytest.approx(0.2) and second["bbox"]["y"] == pytest.approx(0.7)
    assert first["bbox"]["height"] == pytest.approx(0.1) and first["bbox"]["x"] == pytest.approx(0.1)
    frames = result.processing_options["multi_frame"]
    assert frames["layout"] == "vertical-stack-v1" and frames["frames"][1]["y"] == 300
    original = next(item for item in result.items if item.anchor == "original-image")
    assert original.asset_bytes == data and original.asset_mime == "image/tiff"
    assert [cell["frame"] for cell in result.source_metadata["ocr_cells"]] == [1, 2]


def test_single_image_types_follow_png_rules_and_keep_the_original():
    data = samples.image("WEBP")
    result = parse_image(data, SourceFormat.WEBP, _fake_png_read)
    assert result.source_format is SourceFormat.WEBP and result.expected_areas == ["image"]
    line = next(item for item in result.items if item.kind == "paragraph")
    assert line.locator["bbox"]["y"] == pytest.approx(0.4) and line.locator["width_px"] == 900
    original = next(item for item in result.items if item.anchor == "original-image")
    assert original.asset_bytes == data and original.asset_mime == "image/webp"


def test_capability_report_is_parsed_defensively(monkeypatch):
    monkeypatch.setattr(format_capabilities, "_cache", {"at": None, "report": {}})
    monkeypatch.setattr(format_capabilities, "get_text", lambda key: json.dumps({"available": {"odfdo": True, "x": "yes"}}))
    assert format_capabilities.available() == {"odfdo": True, "x": False}
    monkeypatch.setattr(format_capabilities, "_cache", {"at": None, "report": {}})

    def outage(key):
        raise OSError("storage unavailable")
    monkeypatch.setattr(format_capabilities, "get_text", outage)
    assert format_capabilities.available() == {}


def test_docling_failure_or_empty_read_is_never_silent():
    from docgrain_worker.docling_dispatch import mark_document_area

    failed = StructuralParseResult(SourceFormat.XML_XBRL, "docling", "2.130.0", "complete", [], [], [], [],
                                   {"docling_status": "ConversionStatus.FAILURE"})
    mark_document_area(failed)
    assert failed.status == "failed" and failed.issues[0].code == "conversion_failed"
    empty = StructuralParseResult(SourceFormat.HTML, "docling", "2.130.0", "complete", [], [], [], [],
                                  {"docling_status": "ConversionStatus.SUCCESS"})
    mark_document_area(empty)
    assert empty.status == "partial" and empty.expected_areas == ["document"]
    assert empty.issues[0].code == "empty_document"
    original = StructuralParseResult(SourceFormat.DOCX, "docling", "2.130.0", "complete", [], [], [], [],
                                     {"docling_status": "ConversionStatus.FAILURE"})
    mark_document_area(original)
    assert original.status == "complete" and original.issues == []  # the six keep their exact behaviour
