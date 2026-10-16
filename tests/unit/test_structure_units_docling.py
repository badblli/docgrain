"""WP117 parity with docling-core (runs where docling-core is installed: the worker image).

The host venv has no docling-core, so ``structure_units`` reads the stored JSON as dicts there. In
the worker image it uses ``TableItem.export_to_dataframe`` / ``TableData.grid``; both paths must
give the same units, in ``DoclingDocument.iterate_items(with_groups=True)`` order.
"""

import json
from pathlib import Path

import pytest

doc_types = pytest.importorskip("docling_core.types.doc")
from docgrain_records.structure_units import structure_units

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "structure"


def spanned_table():
    TableCell, TableData = doc_types.TableCell, doc_types.TableData

    def cell(r, c, text, span=1, **flags):
        return TableCell(text=text, row_span=1, col_span=span, start_row_offset_idx=r,
                         end_row_offset_idx=r + 1, start_col_offset_idx=c,
                         end_col_offset_idx=c + span, **flags)

    doc = doc_types.DoclingDocument(name="rooms")
    doc.add_heading("Rooms", level=2)
    doc.add_table(TableData(num_rows=4, num_cols=3, table_cells=[
        cell(0, 0, "No", column_header=True), cell(0, 1, "Room", column_header=True),
        cell(0, 2, "Size", column_header=True),
        cell(1, 0, "Garden wing", span=3, row_section=True),
        cell(2, 0, "1"), cell(2, 1, "Standard", row_header=True), cell(2, 2, "24 m²"),
        cell(3, 0, "2"), cell(3, 1, "Family", row_header=True), cell(3, 2, "36 m²")]))
    return doc


def documents():
    for name in ("report", "workbook"):
        raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        yield name, raw
    yield "rooms", spanned_table().export_to_dict()


@pytest.mark.parametrize("name,raw", list(documents()))
def test_docling_core_path_matches_plain_json(name, raw):
    core = [u.to_dict() for u in structure_units(raw, name)]
    plain = [u.to_dict() for u in structure_units(raw, name, use_docling_core=False)]
    assert core == plain and core

    doc = doc_types.DoclingDocument.model_validate(raw)
    order = [item.self_ref for item, _ in doc.iterate_items(with_groups=True)]
    refs = [u["ref"] for u in core]
    assert refs == sorted(refs, key=order.index)
    for unit in core:
        if unit["kind"] == "table" and unit["header_source"] == "column_header":
            table = doc.tables[int(unit["ref"].rsplit("/", 1)[1])]
            frame = table.export_to_dataframe(doc=doc)
            assert unit["fields"] == [str(c) for c in frame.columns]
            assert len(unit["items"]) <= len(frame)
