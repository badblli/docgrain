"""Actual Docling/native adapter comparison, not a mocked parser."""

import importlib.util

import pytest
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.structural import DocumentParser

from tests.unit.test_n2_fidelity import map_result, office_file, verified, workbook_file

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("docling") is None, reason="real worker Docling required"
)


@pytest.mark.parametrize("fmt", [SourceFormat.DOCX, SourceFormat.XLSX])
def test_native_parts_and_chart_survive_real_conversion_and_projection(tmp_path, fmt):
    source = verified(
        office_file(tmp_path) if fmt is SourceFormat.DOCX else workbook_file(tmp_path)
    )
    result = DocumentParser(native_fidelity=True).parse(source, fmt)
    snapshot = map_result(result, source)
    assert (
        snapshot.schema_version == "0.6.0"
        and snapshot.knowledge_revision.processing.mapper_version == "n2-1"
    )
    if fmt is SourceFormat.DOCX:
        assert {n.text for n in snapshot.structure if n.kind == "text_block"} >= {
            "Header exact 987",
            "Footer exact 654",
            "Repeat",
        }
        assert len([n for n in snapshot.structure if n.kind == "asset"]) == 2
    else:
        assert (
            next(n for n in snapshot.structure if n.kind == "chart").source_data[
                "series"
            ][0]["val"]["cells"][0]["value"]
            == 7
        )


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_actual_pdf_table_order_evidence_merge_and_rotated_page(tmp_path, rotation):
    import pymupdf

    path = tmp_path / "native.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 60), "Title before table")
    # First row merges two data columns; next row is a genuine 3-column grid.
    for x in (80, 250, 450):
        page.draw_line((x, 150), (x, 250))
    page.draw_line((350, 200), (350, 250))
    for y in (150, 200, 250):
        page.draw_line((80, y), (450, y))
    page.insert_text((90, 175), "Room")
    page.insert_text((260, 175), "Merged heading")
    page.insert_text((90, 225), "Accessible")
    page.insert_text((260, 225), "7")
    page.insert_text((360, 225), "42")
    page.insert_text((60, 300), "After table exact")
    page.set_rotation(rotation)
    pdf.save(path)
    pdf.close()
    source = verified(path)
    result = DocumentParser(native_fidelity=True).parse(source, SourceFormat.PDF)
    tables = [i for i in result.items if i.kind == "table"]
    assert len(tables) == 1
    assert (
        tables[0].cells[1][1]["value"] == "7" and tables[0].cells[1][2]["value"] == "42"
    )
    assert tables[0].cells[0][1]["col_span"] == 2
    snapshot = map_result(result, source)
    assert any(
        e.locator.kind == "pdf_page" and e.locator.bbox is not None
        for e in snapshot.evidence
    )
    texts = [i.text for i in result.items if i.kind in {"heading", "paragraph"}]
    assert any("Title before" in t for t in texts) and any(
        "After table" in t for t in texts
    )


def test_multicolumn_source_reading_order_is_preserved(tmp_path):
    import pymupdf

    path = tmp_path / "columns.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 60), "Source order")
    page.insert_textbox(
        pymupdf.Rect(60, 100, 260, 230),
        "LEFT first paragraph 123\nLEFT second paragraph 456",
        fontsize=14,
    )
    page.insert_textbox(
        pymupdf.Rect(340, 100, 540, 230),
        "RIGHT first paragraph 789\nRIGHT second paragraph 987",
        fontsize=14,
    )
    pdf.save(path)
    pdf.close()
    result = DocumentParser(native_fidelity=True).parse(
        verified(path), SourceFormat.PDF
    )
    text = " ".join(i.text for i in result.items)
    assert (
        text.index("LEFT first")
        < text.index("LEFT second")
        < text.index("RIGHT first")
        < text.index("RIGHT second")
    )
