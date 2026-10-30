"""WP124: source-local Docling units, independent of canonical ids and file bytes."""

import json
from copy import deepcopy
from pathlib import Path

from docgrain_domain.canonical.version_diff import diff_docling_documents


def doc(*paragraphs):
    texts = [{"self_ref": f"#/texts/{i}", "label": "paragraph", "text": text,
              "prov": [{"page_no": 1, "bbox": {"l": 1, "t": i * 20, "r": 80, "b": i * 20 + 10}}]}
             for i, text in enumerate(paragraphs)]
    return {"body": {"self_ref": "#/body", "children": [{"$ref": t["self_ref"]} for t in texts]},
            "texts": texts, "tables": [], "pictures": []}


def table_doc(price="10"):
    result = doc("Prices")
    result["texts"][0].update(label="section_header", level=1)
    cells = []
    for r, row in enumerate([["Service", "Price"], ["Delivery", price], ["Assembly", "25"]]):
        for c, text in enumerate(row):
            cells.append({"text": text, "column_header": r == 0, "row_header": r > 0 and c == 0,
                          "start_row_offset_idx": r, "end_row_offset_idx": r + 1,
                          "start_col_offset_idx": c, "end_col_offset_idx": c + 1})
    result["tables"] = [{"self_ref": "#/tables/0", "label": "table",
                         "data": {"num_rows": 3, "num_cols": 2, "table_cells": cells}}]
    result["body"]["children"].append({"$ref": "#/tables/0"})
    return result


def test_one_word_is_one_changed_paragraph_with_both_locators():
    before = doc("The delivery takes three days.", "Assembly is included.")
    after = doc("The delivery takes four days.", "Assembly is included.")
    frozen = deepcopy(before)
    result = diff_docling_documents(before, after)
    assert result.has_changes and result.changed_units == 1
    assert result.added_units == result.removed_units == 0
    assert result.unchanged_units == 1
    change, = result.changes
    assert change.before == "The delivery takes three days."
    assert change.after == "The delivery takes four days."
    assert change.kind == "paragraph" and change.operation == "changed"
    assert change.before_locator["ref"] == change.after_locator["ref"] == "#/texts/0"
    assert change.before_locator["provenance"][0]["page_no"] == 1
    assert before == frozen


def test_one_price_cell_addressed_by_row_and_column():
    result = diff_docling_documents(table_doc(), table_doc("12"))
    change, = result.changes
    assert change.kind == "table_cell" and change.operation == "changed"
    assert change.before == "10" and change.after == "12"
    assert change.address["heading_path"] == ["Prices"]
    assert change.address["table"] == "Prices"
    assert change.address["row_header"] == "Delivery"
    assert change.address["column_header"] == "Price"
    assert change.after_locator["row"] == 1 and change.after_locator["column"] == 1


def test_added_and_removed_paragraph_do_not_shift_following_units():
    result = diff_docling_documents(
        doc("An obsolete instruction.", "Assembly is included.", "Delivery takes three days."),
        doc("Assembly is included.", "A completely new warranty covers defects.", "Delivery takes three days."))
    assert result.added_units == result.removed_units == 1
    assert result.changed_units == 0 and result.unchanged_units == 2


def test_resaved_content_unicode_and_whitespace_are_unchanged():
    before, after = doc("Café delivery: １０ units", "Assembly is included."), doc(
        "Cafe\u0301  delivery:\n10\u00a0units", "Assembly is included.")
    after["name"] = "renamed export"
    after["texts"][0]["prov"] = [{"page_no": 3}]
    result = diff_docling_documents(before, after)
    assert result.changes == [] and result.has_changes is False
    assert result.unchanged_units == 2


def test_swapped_paragraphs_and_duplicate_multiplicity():
    result = diff_docling_documents(doc("Alpha paragraph.", "Beta paragraph."),
                                    doc("Beta paragraph.", "Alpha paragraph."))
    assert not result.has_changes and result.unchanged_units == 2
    result = diff_docling_documents(doc("Repeated", "Repeated"), doc("Repeated"))
    assert result.removed_units == 1 and result.unchanged_units == 1


def test_swapped_cell_values_are_changes_and_reordered_rows_are_not():
    before = table_doc()
    after = deepcopy(before)
    cells = after["tables"][0]["data"]["table_cells"]
    cells[3]["text"], cells[5]["text"] = cells[5]["text"], cells[3]["text"]
    result = diff_docling_documents(before, after)
    assert result.changed_units == 2
    after = deepcopy(before)
    for cell in after["tables"][0]["data"]["table_cells"][2:]:
        cell["start_row_offset_idx"] = 3 - cell["start_row_offset_idx"]
        cell["end_row_offset_idx"] = cell["start_row_offset_idx"] + 1
    assert not diff_docling_documents(before, after).has_changes


def test_heading_list_picture_and_key_value_units():
    before = doc("Service information", "Delivery is included.")
    before["texts"][0].update(label="section_header", level=1)
    before["texts"][1]["label"] = "list_item"
    before["pictures"] = [{"self_ref": "#/pictures/0", "label": "picture",
                           "annotations": [{"kind": "description", "text": "A blue sign"}]}]
    before["key_value_items"] = [{"self_ref": "#/key_value_items/0", "graph": {
        "cells": [{"cell_id": 0, "label": "key", "text": "Telephone"},
                  {"cell_id": 1, "label": "value", "text": "12345"}],
        "links": [{"source_cell_id": 0, "target_cell_id": 1, "label": "to_value"}]}}]
    before["body"]["children"] += [{"$ref": "#/pictures/0"}, {"$ref": "#/key_value_items/0"}]
    after = deepcopy(before)
    after["texts"][0]["text"] = "Service details"
    after["texts"][1]["text"] = "Delivery is optional."
    after["pictures"][0]["annotations"][0]["text"] = "A green sign"
    after["key_value_items"][0]["graph"]["cells"][1]["text"] = "67890"
    result = diff_docling_documents(before, after)
    assert {c.kind for c in result.changes} == {"heading", "list_item", "picture_text", "key_value"}
    assert all(c.operation == "changed" for c in result.changes)
    assert next(c for c in result.changes if c.kind == "key_value").address["key"] == "Telephone"


def test_empty_cell_and_rich_cell_references():
    before, after = table_doc(""), table_doc("17")
    change, = diff_docling_documents(before, after).changes
    assert change.before == "" and change.operation == "changed"
    before = table_doc()
    before["texts"].append({"self_ref": "#/texts/1", "text": "10", "label": "text"})
    cell = before["tables"][0]["data"]["table_cells"][3]
    cell.pop("text")
    cell["refs"] = [{"$ref": "#/texts/1"}]
    assert not diff_docling_documents(before, table_doc()).has_changes


def docling_fixture():
    # Real Docling 2.130 export (WP118 fixture): formatted runs live in InlineGroups.
    path = Path(__file__).parents[1] / "fixtures" / "structural" / "wp118-structured.docling.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_real_docling_export_one_word_in_formatted_paragraph_and_one_cell():
    before = docling_fixture()
    assert not diff_docling_documents(before, deepcopy(before)).has_changes
    after = deepcopy(before)
    run = next(t for t in after["texts"] if t["text"] == "lists")
    run["text"] = run["orig"] = "names"
    change, = diff_docling_documents(before, after).changes
    assert change.operation == "changed" and change.kind == "paragraph"
    assert change.before.startswith("Welcome! This guide lists all services.")
    assert change.after.startswith("Welcome! This guide names all services.")
    assert change.after_locator["ref"] == "#/groups/0"
    after = deepcopy(before)
    cell = next(c for c in after["tables"][0]["data"]["table_cells"] if c["text"] == "1.800 TL")
    cell["text"] = "1.950 TL"
    change, = diff_docling_documents(before, after).changes
    assert (change.kind, change.before, change.after) == ("table_cell", "1.800 TL", "1.950 TL")
    assert change.address["row_header"] == "Family" and change.address["column_header"] == "Price"


def test_renamed_row_label_and_caption_keep_cells_matched():
    before, after = table_doc(), table_doc()
    after["tables"][0]["data"]["table_cells"][2]["text"] = "Shipping"
    change, = diff_docling_documents(before, after).changes
    assert (change.before, change.after, change.kind) == ("Delivery", "Shipping", "table_cell")
    for document, caption in ((before, "Price list"), (after, "Price list 2027")):
        document["texts"].append({"self_ref": "#/texts/1", "label": "caption", "text": caption})
        document["tables"][0]["captions"] = [{"$ref": "#/texts/1"}]
    after["tables"][0]["data"]["table_cells"][2]["text"] = "Delivery"
    change, = diff_docling_documents(before, after).changes
    assert (change.kind, change.before, change.after) == ("paragraph", "Price list", "Price list 2027")


def test_nested_heading_renames_keep_child_paragraphs_matched():
    before = doc("Services", "Delivery", "Delivery takes three days.")
    before["texts"][0].update(label="section_header", level=1)
    before["texts"][1].update(label="section_header", level=2)
    after = deepcopy(before)
    after["texts"][0]["text"] = "Our services"
    after["texts"][1]["text"] = "Delivery options"
    after["texts"][2]["text"] = "Delivery takes four days."
    result = diff_docling_documents(before, after)
    assert result.changed_units == 3 and result.added_units == result.removed_units == 0
    paragraph = next(c for c in result.changes if c.kind == "paragraph")
    assert paragraph.address["heading_path"] == ["Our services", "Delivery options"]


def test_table_without_header_flags_uses_first_row_and_column_labels():
    before = table_doc()
    for cell in before["tables"][0]["data"]["table_cells"]:
        cell["column_header"] = cell["row_header"] = False
    after = deepcopy(before)
    after["tables"][0]["data"]["table_cells"][3]["text"] = "11"
    change, = diff_docling_documents(before, after).changes
    assert change.address["row_header"] == "Delivery" and change.address["column_header"] == "Price"


def test_furniture_and_rewritten_document_are_handled():
    before = doc("Page 1 of 3", "Delivery takes three days.")
    before["texts"][0]["content_layer"] = "furniture"
    after = deepcopy(before)
    after["texts"][0]["text"] = "Page 1 of 4"
    assert not diff_docling_documents(before, after).has_changes
    old = doc(*(f"Old clause number {i} about returns." for i in range(300)))
    new = doc(*(f"Completely different wording {i * 7} for warranty." for i in range(300)))
    result = diff_docling_documents(old, new)
    assert result.added_units + result.changed_units == 300
