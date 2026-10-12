"""WP117: structural units from stored DoclingDocument JSON and first deterministic grouping.

The fixtures in tests/fixtures/structure were exported by docling-core 2.101 (build_fixtures.py,
run in the worker image); docling-core itself is not installed on the host, so they load as dicts.
"""

import importlib.util
import json
import random
from pathlib import Path

import pytest
from docgrain_records.structure_units import group_units, structure_units, unit_counts

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "structure"
spec = importlib.util.spec_from_file_location(
    "structure_coverage", Path(__file__).resolve().parents[2] / "benchmarks/structure_coverage.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def units():
    return structure_units(load("report"), "doc-report") + structure_units(load("workbook"), "doc-book")


def by_kind(units, kind):
    return [u for u in units if u.kind == kind]


def test_units_from_tables_lists_key_values_and_sheets(units):
    assert unit_counts(units) == {"table": 2, "list": 1, "key_value": 1, "sheet": 1}
    report_table, book_table = by_kind(units, "table")
    assert (report_table.name, report_table.name_source) == ("Restaurants", "heading")
    assert report_table.fields == ["Restaurant", "Hours"]
    assert report_table.name_field == "Restaurant"
    assert report_table.header_source == "column_header"
    assert [(i.name, i.values) for i in report_table.items] == [
        ("Lagoon Restaurant", {"Hours": "07:00-10:30"}), ("Sunset Grill", {"Hours": "12:30-17:00"})]
    cell = report_table.items[0].evidence["Hours"]
    assert (cell.document_id, cell.ref, cell.row, cell.col, cell.page_no) == (
        "doc-report", "#/tables/0", 1, 1, 1)
    assert cell.bbox and cell.text == "07:00-10:30"
    assert report_table.items[0].name_evidence.col == 0

    sheet = by_kind(units, "sheet")[0]
    assert sheet.name == "F&B saatleri" and sheet.children == [book_table.id]
    assert (book_table.name, book_table.name_source, book_table.sheet) == (
        "F&B saatleri", "sheet", "F&B saatleri")
    assert book_table.fields == ["Restoran", "Açılış", "Kapanış"]

    pools = by_kind(units, "list")[0]
    assert (pools.name, pools.name_source) == ("Havuzlar", "heading")
    assert [i.name for i in pools.items] == ["Ana havuz", "Çocuk havuzu", "Kapalı havuz"]
    assert pools.items[2].values == {"detail": "08:00-20:00"}
    assert pools.items[0].name_evidence.ref == "#/texts/3"
    assert pools.heading_path == ["Hotel guide", "Havuzlar"]

    key_values = by_kind(units, "key_value")[0]
    assert (key_values.name, key_values.fields) == ("Genel bilgiler", ["Check-in", "Check-out"])
    assert key_values.items[0].values == {"Check-in": "14:00", "Check-out": "12:00"}
    assert key_values.items[0].evidence["Check-in"].page_no == 2


def test_restaurant_units_join_one_collection_and_same_item_is_one_record(units):
    grouping = group_units(units)
    restaurants = next(c for c in grouping.collections if "table" in c.kinds)
    assert restaurants.units == ["doc-book#/tables/0", "doc-report#/tables/0"]
    assert restaurants.name == "Restaurants"
    assert set(restaurants.names) == {"Restaurants", "F&B saatleri"}
    assert restaurants.joined_by == ["items"]
    records = {r.key: r for r in restaurants.records}
    assert sorted(records) == ["beach bar", "lagoon restaurant", "sunset grill"]
    lagoon = records["lagoon restaurant"]
    assert lagoon.documents == ["doc-book", "doc-report"]
    assert {(s.document_id, s.ref, s.row) for s in lagoon.sources} == {
        ("doc-book", "#/tables/0", 1), ("doc-report", "#/tables/0", 1)}
    assert lagoon.values == {"Hours": ["07:00-10:30"], "Açılış": ["07:00"], "Kapanış": ["10:30"]}

    pools = next(c for c in grouping.collections if c.kinds == ["list"])
    assert pools.name == "Havuzlar" and len(pools.records) == 3

    key_values = next(c for c in grouping.collections if c.kinds == ["key_value"])
    assert key_values.fields == ["Check-in", "Check-out"]
    assert key_values.records == [] and key_values.unnamed_items == 1
    assert len(grouping.collections) == 3 and grouping.ambiguous == []


def test_grouping_is_deterministic(units):
    first = group_units(units).to_dict()
    shuffled = list(units)
    random.Random(7).shuffle(shuffled)
    assert group_units(shuffled).to_dict() == first


def cell(r, c, text, *, header=False, row_header=False, section=False, span=1):
    return {"text": text, "row_span": 1, "col_span": span, "start_row_offset_idx": r,
            "end_row_offset_idx": r + 1, "start_col_offset_idx": c, "end_col_offset_idx": c + span,
            "column_header": header, "row_header": row_header, "row_section": section}


def document(*tables, headings=()):
    texts = [{"self_ref": f"#/texts/{i}", "label": "section_header", "level": 1, "text": text,
              "children": [], "prov": []} for i, text in enumerate(headings)]
    items = [{"self_ref": f"#/tables/{i}", "label": "table", "children": [], "captions": [],
              "prov": [{"page_no": 3, "bbox": {"l": 0, "t": 0, "r": 1, "b": 1}, "charspan": [0, 0]}],
              "data": {"table_cells": cells, "num_rows": rows, "num_cols": cols}}
             for i, (cells, rows, cols) in enumerate(tables)]
    order = []
    for i in range(max(len(texts), len(items))):
        order += [{"$ref": f"#/texts/{i}"}] if i < len(texts) else []
        order += [{"$ref": f"#/tables/{i}"}] if i < len(items) else []
    return {"schema_name": "DoclingDocument", "body": {"self_ref": "#/body", "children": order},
            "groups": [], "texts": texts, "tables": items, "key_value_items": []}


def grid(rows, header_rows=1):
    return ([cell(r, c, text, header=r < header_rows) for r, row in enumerate(rows)
             for c, text in enumerate(row)], len(rows), len(rows[0]))


def test_row_header_section_rows_and_first_row_fallback():
    cells = [cell(0, 0, "No", header=True), cell(0, 1, "Room", header=True),
             cell(0, 2, "Size", header=True),
             cell(1, 0, "Garden wing", section=True, span=3),
             cell(2, 0, "1"), cell(2, 1, "Standard", row_header=True), cell(2, 2, "24 m²"),
             cell(3, 0, "2"), cell(3, 1, "Family", row_header=True), cell(3, 2, "36 m²")]
    plain = [cell(r, c, t) for r, row in enumerate([["Spa", "Hours"], ["Hamam", "09:00"]])
             for c, t in enumerate(row)]
    rooms, spa = structure_units(document((cells, 4, 3), (plain, 2, 2)), "doc")
    assert rooms.name_field == "Room" and rooms.fields == ["No", "Room", "Size"]
    assert [(i.name, i.section, i.values) for i in rooms.items] == [
        ("Standard", "Garden wing", {"No": "1", "Size": "24 m²"}),
        ("Family", "Garden wing", {"No": "2", "Size": "36 m²"})]
    assert (spa.header_source, spa.fields, spa.items[0].name) == ("first_row", ["Spa", "Hours"], "Hamam")
    assert spa.name == "Spa" and spa.name_source == "name_field"


def test_weak_overlap_is_listed_not_joined():
    left = grid([["Room", "Size", "View", "Beds"], ["Standard", "24", "Sea", "2"]])
    right = grid([["Room", "Size", "Price", "Season"], ["Suite", "60", "300", "May"]])
    units = structure_units(document(left, headings=["Rooms A"]), "a") + structure_units(
        document(right, headings=["Rates"]), "b")
    grouping = group_units(units)
    assert len(grouping.collections) == 2
    (join,) = grouping.ambiguous
    assert (join.left, join.right, join.reason) == ("a#/tables/0", "b#/tables/0", "weak_overlap")
    assert join.field_jaccard == pytest.approx(2 / 6, abs=1e-3)


def test_strong_field_overlap_and_names_join():
    first = grid([["Room", "Size", "View"], ["Standard", "24", "Sea"]])
    second = grid([["ROOM", "size", "Vıew"], ["Suite", "60", "Garden"]])
    units = structure_units(document(first, headings=["Odalar"]), "a") + structure_units(
        document(second, headings=["Rooms"]), "b")
    (rooms,) = group_units(units).collections
    assert rooms.joined_by == ["fields"] and len(rooms.records) == 2


def test_join_bridging_two_collections_is_ambiguous():
    rooms_a = grid([["Room", "Size", "View"], ["Standard", "24", "Sea"]])
    rooms_b = grid([["Room", "Size", "View"], ["Suite", "60", "Sea"]])
    bars_a = grid([["Bar", "Hours"], ["Lobby Bar", "10:00"], ["Pool Bar", "11:00"]])
    bars_b = grid([["Bar", "Open"], ["Lobby Bar", "10:00"], ["Pool Bar", "12:00"]])
    # One odd table shares one item with each group: listed, never used to merge the two.
    odd = grid([["Name", "Note"], ["Standard", "x"], ["Lobby Bar", "y"]])
    units = (structure_units(document(rooms_a, rooms_b, headings=["Rooms", "Rooms"]), "a")
             + structure_units(document(bars_a, bars_b, headings=["Bars", "Bars"]), "b")
             + structure_units(document(odd, headings=["Misc"]), "c"))
    grouping = group_units(units)
    groups = sorted(sorted(c.units) for c in grouping.collections)
    assert groups == [["a#/tables/0", "a#/tables/1", "c#/tables/0"], ["b#/tables/0", "b#/tables/1"]]
    bridges = [a for a in grouping.ambiguous if a.reason == "would_bridge_collections"]
    assert [(a.left, a.right) for a in bridges] == [("b#/tables/0", "c#/tables/0"),
                                                    ("b#/tables/1", "c#/tables/0")]


def test_benchmark_compare_and_dry_run(tmp_path, capsys):
    with pytest.raises(SystemExit) as help_exit:
        benchmark.main(["--help"])
    assert help_exit.value.code == 0
    assert "structure coverage" in capsys.readouterr().out.lower()

    assert benchmark.main(["--fixtures", str(FIXTURES), "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "structure-coverage.json").read_text(encoding="utf-8"))
    (ws,) = report["workspaces"]
    assert ws["units"] == {"table": 2, "list": 1, "key_value": 1, "sheet": 1}
    assert ws["candidate_collections"] == 3 and ws["candidate_records"] == 6
    comparison = ws["comparison"]
    assert comparison["published_only"] == ["spa"]
    assert [c["name"] for c in comparison["structure_only"]] == ["Genel bilgiler"]
    rows = {row["collection"]: row for row in comparison["collections"]}
    assert rows["restaurants"]["record_name_share"] == 0.5
    assert rows["restaurants"]["value_share"] == 0.5
    assert rows["pools"]["record_name_share"] == 1.0
    assert comparison["record_name_share"] == 0.6
    markdown = (tmp_path / "structure-coverage.md").read_text(encoding="utf-8")
    assert "| restaurants | 2 | Restaurants (3) | 50.0% | 50.0% |" in markdown


def test_missing_docling_and_no_publication():
    result = benchmark.measure_workspace(
        [{"id": "d", "filename": "x.txt", "mime_type": "text/plain", "docling": None,
          "source": "missing"}], None)
    assert result["documents_with_docling"] == 0 and result["comparison"] is None
    assert result["units"] == {"table": 0, "list": 0, "key_value": 0, "sheet": 0}
