"""Regenerate the WP117 synthetic DoclingDocument fixtures with the real docling-core types.

docling-core is not installed on the host venv, so the JSON files next to this script are checked in
and the host tests read them as plain dicts. Regenerate them inside the worker image (docling-core
2.101) with:

    docker exec -i docgrain-worker-1 python - < tests/fixtures/structure/build_fixtures.py \
        > data/structure-fixtures.json

and split the printed object into ``report.json`` / ``workbook.json``. Neutral, invented content only.
"""

import json

from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    GroupLabel,
    ProvenanceItem,
    TableCell,
    TableData,
)
from docling_core.types.doc.document import GraphCell, GraphData, GraphLink
from docling_core.types.doc.labels import GraphCellLabel, GraphLinkLabel


def prov(page, top, text=""):
    return ProvenanceItem(page_no=page, bbox=BoundingBox(l=50, t=top, r=500, b=top + 14),
                          charspan=(0, len(text)))


def table(rows, *, header_rows=1, top=100.0):
    cells = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            cells.append(TableCell(
                text=text, row_span=1, col_span=1, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                start_col_offset_idx=c, end_col_offset_idx=c + 1, column_header=r < header_rows,
                bbox=BoundingBox(l=50 + 150 * c, t=top + 20 * r, r=190 + 150 * c, b=top + 18 + 20 * r)))
    return TableData(table_cells=cells, num_rows=len(rows), num_cols=len(rows[0]))


def report():
    doc = DoclingDocument(name="report")
    doc.add_title("Hotel guide", prov=prov(1, 40, "Hotel guide"))
    doc.add_heading("Restaurants", level=1, prov=prov(1, 70, "Restaurants"))
    doc.add_table(table([["Restaurant", "Hours"],
                         ["Lagoon Restaurant", "07:00-10:30"],
                         ["Sunset Grill", "12:30-17:00"]]),
                  prov=prov(1, 100))
    doc.add_heading("Havuzlar", level=1, prov=prov(1, 200, "Havuzlar"))
    pools = doc.add_list_group()
    for index, name in enumerate(["Ana havuz", "Çocuk havuzu", "Kapalı havuz: 08:00-20:00"]):
        doc.add_list_item(name, parent=pools, prov=prov(1, 220 + 16 * index, name))
    doc.add_heading("Genel bilgiler", level=1, prov=prov(2, 40, "Genel bilgiler"))
    area = doc.add_group(label=GroupLabel.KEY_VALUE_AREA, name="key-value area")
    cells, links = [], []
    for index, (key, value) in enumerate([("Check-in", "14:00"), ("Check-out", "12:00")]):
        cells.append(GraphCell(label=GraphCellLabel.KEY, cell_id=2 * index, text=key, orig=key,
                               prov=prov(2, 60 + 16 * index, key)))
        cells.append(GraphCell(label=GraphCellLabel.VALUE, cell_id=2 * index + 1, text=value,
                               orig=value, prov=prov(2, 60 + 16 * index, value)))
        links.append(GraphLink(label=GraphLinkLabel.TO_VALUE, source_cell_id=2 * index,
                               target_cell_id=2 * index + 1))
    doc.add_key_values(graph=GraphData(cells=cells, links=links), parent=area, prov=prov(2, 60))
    doc.add_text(DocItemLabel.TEXT, "Prices are per person.", prov=prov(2, 120, "x"))
    return doc


def workbook():
    doc = DoclingDocument(name="workbook")
    sheet = doc.add_group(label=GroupLabel.SHEET, name="F&B saatleri")
    doc.add_table(table([["Restoran", "Açılış", "Kapanış"],
                         ["Lagoon Restaurant", "07:00", "10:30"],
                         ["Beach Bar", "10:00", "18:00"]]),
                  parent=sheet, prov=prov(1, 0))
    return doc


if __name__ == "__main__":
    print(json.dumps({"report": report().export_to_dict(), "workbook": workbook().export_to_dict()},
                     ensure_ascii=False, indent=1))
