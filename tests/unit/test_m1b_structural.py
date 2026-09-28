"""M1b boundary tests that do not require a Docling model download."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from zipfile import ZipFile

import pymupdf
import pytest
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, SourceVersion
from docgrain_domain.source_format import (
    CorruptSource,
    FormatMismatch,
    SourceFormat,
    declared_format,
    verify_format,
)
from docgrain_worker.canonical_mapper import CanonicalMapper
from docgrain_worker.pdf_geometry import normalized_pdf_box
from docgrain_worker.structural import DocumentParser, VerifiedSource


def test_format_dispatch_and_signature_rejection() -> None:
    assert declared_format("a.PDF", "application/octet-stream") is SourceFormat.PDF
    with pytest.raises(FormatMismatch):
        declared_format("a.docx", "application/pdf")
    with pytest.raises(FormatMismatch):
        declared_format("a.exe", "application/octet-stream")
    with pytest.raises(FormatMismatch):
        verify_format(b"not a PDF", SourceFormat.PDF)
    with pytest.raises(CorruptSource):
        verify_format(b"PKbroken", SourceFormat.DOCX)
    with pytest.raises(CorruptSource):
        verify_format(b"\xff", SourceFormat.TXT)
    archive = io.BytesIO()
    with ZipFile(archive, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(FormatMismatch):
        verify_format(archive.getvalue(), SourceFormat.DOCX)


def test_txt_offsets_and_repeatable_canonical_ids(tmp_path) -> None:
    path = tmp_path / "multilingual.txt"
    data = "\ufeff# Başlık\r\nİzmir 🌊\n\nSecond line\r\n".encode("utf-8")
    path.write_bytes(data)
    verified = VerifiedSource(path, hashlib.sha256(data).hexdigest(), len(data))
    parsed = DocumentParser().parse(verified, SourceFormat.TXT)
    assert parsed.status == "complete"
    assert [item.kind for item in parsed.items] == ["heading", "paragraph", "paragraph"]
    decoded = data.decode("utf-8-sig")
    assert all(decoded[item.locator["start"]:item.locator["end"]] == item.text for item in parsed.items)
    source = SourceVersion(id="source-txt", document_id="document-txt", workspace_id="workspace",
                           content_sha256=verified.content_sha256, storage_uri="fixture://source",
                           storage_version="v1", byte_size=len(data), mime_type="text/plain",
                           filename="multilingual.txt", recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    mapper = CanonicalMapper()
    first = mapper.map(parsed, source, revision_id="revision-1", created_at=source.recorded_at)
    second = mapper.map(DocumentParser().parse(verified, SourceFormat.TXT), source,
                        revision_id="revision-2", created_at=source.recorded_at)
    assert [node.id for node in first.structure] == [node.id for node in second.structure]
    assert first.schema_version == "0.2.0"
    assert first.entities == first.records == first.relations == []
    assert first.structure[0].children[0] == first.structure[1].id


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_pdf_bbox_rotations(rotation: int) -> None:
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.set_rotation(rotation)
    raw = {"l": 60, "t": 720, "r": 120, "b": 680, "coord_origin": "BOTTOMLEFT"}
    box = normalized_pdf_box(raw, (600, 800), page)
    assert box is not None
    assert 0 <= box.x <= 1 and 0 <= box.y <= 1
    assert box.width > 0 and box.height > 0
    if rotation in (0, 180):
        assert box.width == pytest.approx(0.1)
        assert box.height == pytest.approx(0.05)
    else:
        assert box.width == pytest.approx(0.05)
        assert box.height == pytest.approx(0.1)
    document.close()


def test_pdf_crop_and_invalid_bbox() -> None:
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.set_cropbox(pymupdf.Rect(20, 30, 580, 770))
    full_crop = {"l": 0, "t": 740, "r": 560, "b": 0, "coord_origin": "BOTTOMLEFT"}
    box = normalized_pdf_box(full_crop, (560, 740), page)
    assert box is not None
    assert box.x == pytest.approx(0) and box.y == pytest.approx(0)
    assert box.width == pytest.approx(1) and box.height == pytest.approx(1)
    assert normalized_pdf_box(None, (560, 740), page) is None
    assert normalized_pdf_box({**full_crop, "r": 600}, (560, 740), page) is None
    document.close()


def test_old_schema_artifact_is_preserved_and_new_cells_are_versioned() -> None:
    from pathlib import Path

    fixture = Path("tests/fixtures/canonical/generic-pdf.json")
    value = json.loads(fixture.read_text(encoding="utf-8"))
    value["structure"][-1]["rows"][0][0]["formula"] = "=A1+1"
    with pytest.raises(ValueError, match="0.2.0 table cell fields"):
        CanonicalKnowledgeSnapshot.model_validate(value)
    value["schema_version"] = "0.2.0"
    assert CanonicalKnowledgeSnapshot.model_validate(value).structure[-1].rows[0][0].formula == "=A1+1"
