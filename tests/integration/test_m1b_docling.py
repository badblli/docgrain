"""Real Docling probes against generated, synthetic multi-format documents."""

from __future__ import annotations

import hashlib
import importlib.util
from datetime import UTC, datetime

import pytest
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.canonical_mapper import CanonicalMapper
from docgrain_worker.structural import DocumentParser, VerifiedSource

pytestmark = pytest.mark.skipif(importlib.util.find_spec("docling") is None,
                                reason="real Docling integration requires worker image")


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    from tests.fixtures.structural.generate import create_corpus

    return create_corpus(tmp_path_factory.mktemp("m1b-corpus"))


def parse(path, source_format):
    data = path.read_bytes()
    source = VerifiedSource(path, hashlib.sha256(data).hexdigest(), len(data))
    result = DocumentParser().parse(source, source_format)
    if source_format is not SourceFormat.TXT:
        assert result.parser_version == "2.130.0"
    assert result.status != "failed"
    return result, source


def test_docx_headings_tables_and_picture(corpus):
    headings, _ = parse(corpus["docx-headings"], SourceFormat.DOCX)
    assert any(item.kind == "heading" and item.text == "Heading One" for item in headings.items)
    assert any(item.kind == "paragraph" and "First paragraph" in item.text for item in headings.items)
    pictures = [item for item in headings.items if item.kind == "picture"]
    assert pictures and pictures[0].asset_bytes and pictures[0].locator["kind"] == "docx_block"
    tables, _ = parse(corpus["docx-table"], SourceFormat.DOCX)
    assert any(item.kind == "table" and item.cells[1][1]["value"] == "2" for item in tables.items)
    assert all(item.locator is not None for item in tables.items)


def test_xlsx_sheet_formula_merged_and_assets(corpus):
    result, verified = parse(corpus["xlsx"], SourceFormat.XLSX)
    assert result.source_metadata["docling_status"].endswith("SUCCESS")
    assert result.expected_areas == ["sheet:Data", "sheet:Second"]
    tables = [item for item in result.items if item.kind == "table"]
    assert tables
    formulas = [cell for table in tables for row in table.cells for cell in row if cell.get("formula")]
    assert any(cell["formula"] == "=B2*2" and cell["cached_value"] is None for cell in formulas)
    assert any(cell.get("col_span") == 2 for table in tables for row in table.cells for cell in row)
    assert any(item.kind == "chart" for item in result.items)
    pictures = [item for item in result.items if item.kind == "picture"]
    assert pictures and pictures[0].asset_bytes
    assert any(issue.code == "missing_cached_value" for issue in result.issues)
    for picture in pictures:
        picture.asset_path = "fixture://source-image"
    source = SourceVersion(id="source-xlsx", document_id="document-xlsx", workspace_id="workspace",
                           content_sha256=verified.content_sha256, storage_uri="fixture://workbook",
                           storage_version="v1", byte_size=verified.byte_size,
                           mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename="workbook.xlsx", recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    snapshot = CanonicalMapper().map(result, source, revision_id="revision-xlsx", created_at=source.recorded_at)
    assert snapshot.schema_version == "0.2.0" and snapshot.artifacts
    assert snapshot.metadata["structural_parse"]["coverage"]["status"] == "partial"


def test_pdf_provenance_and_low_text(corpus):
    basic, _ = parse(corpus["basic"], SourceFormat.PDF)
    assert basic.source_metadata["pages"]["1"]["size"]["width"] > 0
    assert any(item.locator and item.locator.get("bbox", {}).get("coord_origin") == "BOTTOMLEFT"
               for item in basic.items)
    scanned, _ = parse(corpus["scanned-low-text"], SourceFormat.PDF)
    assert scanned.status == "partial"
    assert any(issue.code == "low_text_page" for issue in scanned.issues)


@pytest.mark.parametrize("name", ["table", "multicolumn", "rotated90", "rotated180", "rotated270", "cropped", "image-heavy"])
def test_pdf_corpus_mapping(corpus, name):
    result, verified = parse(corpus[name], SourceFormat.PDF)
    if name == "table":
        assert any(item.kind == "table" and item.cells[1][1]["value"] == "2" for item in result.items)
        assert any(issue.code == "docling_missed_table" for issue in result.issues)
    source = SourceVersion(id=f"source-{name}", document_id=f"document-{name}", workspace_id="workspace",
                           content_sha256=verified.content_sha256, storage_uri=f"fixture://{name}",
                           storage_version="v1", byte_size=verified.byte_size, mime_type="application/pdf",
                           filename=f"{name}.pdf", recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    snapshot = CanonicalMapper().map(result, source, revision_id=f"revision-{name}",
                                     created_at=source.recorded_at, pdf_path=verified.path)
    assert snapshot.structure and snapshot.evidence
    assert all(box.bbox is None or 0 <= box.bbox.x <= 1 for box in
               (e.locator for e in snapshot.evidence if e.locator.kind == "pdf_page"))
