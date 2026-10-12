"""WP118: TXT structure from Docling's Markdown backend with exact source text; table header flags.

Host tests read a DoclingDocument JSON that Docling 2.130 (worker image) produced from the TXT fixture
next to it (`wp118-structured.docling.json`); the real conversion runs in tests/integration.
"""

import json
import re
import unicodedata
from collections import Counter
from hashlib import sha256
from pathlib import Path

from docgrain_domain.canonical.ai_output import context_projection, project_ai
from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunk_set
from docgrain_domain.canonical.lifecycle import ProcessingSpec, processing_revision_id
from docgrain_records.structure_context import (
    StructureIndex,
    pin_structure,
    row_header_column,
    without_structure,
)
from docgrain_records.structure_units import structure_units
from docgrain_worker.canonical_mapper import CanonicalMapper
from docgrain_worker.structural import (
    StructuralItem,
    VerifiedSource,
    _docling_cells,
    _txt,
)
from docgrain_worker.txt_structure import align, docling_blocks

from tests.fixtures.lifecycle import mapped_snapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "structural"


def words(text: str) -> Counter:
    return Counter(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def fixture():
    text = (FIXTURES / "wp118-structured.txt").read_bytes().decode("utf-8-sig")
    raw = json.loads((FIXTURES / "wp118-structured.docling.json").read_text(encoding="utf-8"))
    return text, raw


def test_docling_markdown_blocks_rewrite_text_so_only_structure_is_used():
    _, raw = fixture()
    blocks = docling_blocks(raw)
    kinds = [b.kind for b in blocks]
    assert kinds.count("heading") == 5 and kinds.count("list_item") == 5 and kinds.count("table") == 1
    # Docling drops the emphasis markers and splits the paragraph into inline items.
    texts = [t["text"] for t in raw["texts"]]
    assert "guide" in texts and "*guide*" not in " ".join(texts)


def test_txt_items_keep_exact_spans_and_docling_structure():
    text, raw = fixture()
    items = align(text, raw)
    for item in items:
        assert text[item.start:item.end] == item.text
    headings = [(i.text, i.level) for i in items if i.kind == "heading"]
    assert headings == [("Guest Guide", 1), ("Rooms", 2), ("Ground Floor", 3), ("Roof Floor", 3),
                        ("Setext Title", 1)]
    lists = [i.text for i in items if i.kind == "list_item"]
    assert lists[0] == "Sea view room: 32 m², 2 guests"
    assert lists[1].startswith("Garden room: 28 m²") and lists[1].endswith("continued line")
    assert lists[2:] == ["Star bullet", "1. Suite: 45 m²", "2) Family room"]  # ordered numbers are kept
    paragraph = next(i for i in items if i.text.startswith("Welcome"))
    assert "*guide*" in paragraph.text and "__all__" in paragraph.text and paragraph.line_range == (3, 4)
    assert any(i.text.startswith("Last line #tag 50% [link](http://example.com/x)") for i in items)
    table = next(i for i in items if i.kind == "table")
    assert [[c["value"] for c in row] for row in table.cells] == [
        ["Room", "Guests", "Price"], ["Suite", "2", "1.200 TL"], ["Family", "4", "1.800 TL"]]
    assert all(c["source_attributes"] == {"column_header": True} for c in table.cells[0])
    assert all("source_attributes" not in c for row in table.cells[1:] for c in row)
    for row in table.cells:
        for cell in row:
            assert text[cell["locator"]["start"]:cell["locator"]["end"]] == cell["value"]


def test_txt_word_recall_is_complete_against_the_old_reader(tmp_path):
    text, raw = fixture()
    path = tmp_path / "structured.txt"
    path.write_bytes(text.encode("utf-8"))
    data = path.read_bytes()
    old = _txt(VerifiedSource(path, sha256(data).hexdigest(), len(data)))
    old_words = words("\n".join(i.text for i in old.items))
    new_words = words("\n".join(i.text for i in align(text, raw)))
    assert sum((old_words & new_words).values()) == old_words.total()
    assert sum((words(text) & new_words).values()) == words(text).total()


def test_lines_docling_does_not_cover_stay_as_exact_paragraphs():
    text = "Intro line\n\n<!-- comment kept -->\n\n- item one\n"
    raw = {"body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/groups/0"}]},
           "texts": [{"self_ref": "#/texts/0", "label": "text", "text": "Intro line", "children": []},
                     {"self_ref": "#/texts/1", "label": "list_item", "text": "item one", "children": []}],
           "groups": [{"self_ref": "#/groups/0", "label": "list", "children": [{"$ref": "#/texts/1"}]}]}
    items = align(text, raw)
    assert [(i.kind, i.text) for i in items] == [
        ("paragraph", "Intro line"), ("paragraph", "<!-- comment kept -->"), ("list_item", "item one")]


def test_docling_cell_header_flags_reach_the_canonical_snapshot():
    table = {"data": {"num_rows": 2, "num_cols": 2, "table_cells": [
        {"text": "Room", "start_row_offset_idx": 0, "start_col_offset_idx": 0, "column_header": True},
        {"text": "Size", "start_row_offset_idx": 0, "start_col_offset_idx": 1, "column_header": True},
        {"text": "Suite", "start_row_offset_idx": 1, "start_col_offset_idx": 0, "row_header": True},
        {"text": "45", "start_row_offset_idx": 1, "start_col_offset_idx": 1}]}}
    cells = _docling_cells(table)
    assert cells[0][0]["source_attributes"] == {"column_header": True}
    assert cells[1][0]["source_attributes"] == {"row_header": True}
    assert "source_attributes" not in cells[1][1]

    _, result, source, spec = mapped_snapshot()
    result.items = [StructuralItem("table", "t", {"kind": "text_span", "start": 0, "end": 5}, cells=cells)]
    current = spec.model_copy(update={"schema_version": "0.6.0"})
    snapshot = CanonicalMapper().map(result, source, processing=current, created_at=source.recorded_at,
                                     revision_id=processing_revision_id(source.id, current))
    node = next(n for n in snapshot.structure if n.kind == "table")
    assert node.rows[0][1].source_attributes == {"column_header": True}
    assert node.rows[1][0].source_attributes == {"row_header": True}
    assert node.rows[1][1].source_attributes is None
    # Older snapshot schemas cannot carry source facts: the header flags are left out, nothing fails.
    legacy = CanonicalMapper().map(result, source, processing=spec, created_at=source.recorded_at,
                                   revision_id=processing_revision_id(source.id, spec))
    assert all(c.source_attributes is None for n in legacy.structure if n.kind == "table"
               for row in n.rows for c in row)
    assert isinstance(spec, ProcessingSpec)


def table_context(row_header_col):
    _, result, source, spec = mapped_snapshot()
    spec = spec.model_copy(update={"schema_version": "0.6.0"})

    def cell(value, **flags):
        return {"value": value, **({"source_attributes": flags} if flags else {})}

    rows = [[cell("No", column_header=True), cell("Room", column_header=True), cell("Size", column_header=True)]]
    for number, name, size in (("1", "Garden", "24"), ("2", "Family", "36")):
        rows.append([cell(number, row_header=row_header_col == 0), cell(name, row_header=row_header_col == 1),
                     cell(size)])
    result.items = [StructuralItem("heading", "h", {"kind": "text_span", "start": 0, "end": 5}, text="Rooms"),
                    StructuralItem("table", "t", {"kind": "text_span", "start": 10, "end": 50}, cells=rows)]
    snapshot = CanonicalMapper().map(result, source, processing=spec, created_at=source.recorded_at,
                                     revision_id=processing_revision_id(source.id, spec))
    output = project_ai(snapshot, derive_chunk_set(snapshot, ChunkingSpec()))
    return pin_structure(context_projection(output), snapshot.model_dump(mode="json")), snapshot


def test_structure_context_uses_docling_row_header_column():
    context, snapshot = table_context(row_header_col=1)
    table = next(n for n in snapshot.model_dump(mode="json")["structure"] if n["kind"] == "table")
    assert row_header_column(table) == 1
    index = StructureIndex(context)
    key = next(k for k, body in index.bodies.items() if body.startswith("|"))
    assert f'{key} table={{"row_header_column": 1}}' in context
    located = index.at(key + ' cell={"row":2,"column":3}')
    assert (located.row_header, located.column_header) == ("Family", "Size")
    # Pins never reach a prompt.
    assert "table=" not in without_structure(context)
    # Without Docling's flag the first column stays the row header (WP114 behaviour).
    unflagged, _ = table_context(row_header_col=None)
    assert "table=" not in unflagged
    index = StructureIndex(unflagged)
    key = next(k for k, body in index.bodies.items() if body.startswith("|"))
    assert index.at(key + ' cell={"row":2,"column":3}').row_header == "2"


def test_structure_units_report_where_the_item_name_column_came_from():
    def cell(r, c, text, **flags):
        return {"text": text, "start_row_offset_idx": r, "end_row_offset_idx": r + 1, "start_col_offset_idx": c,
                "end_col_offset_idx": c + 1, "row_span": 1, "col_span": 1, **flags}

    def document(flag_name_column):
        cells = [cell(0, 0, "No", column_header=True), cell(0, 1, "Room", column_header=True),
                 cell(1, 0, "1"), cell(1, 1, "Garden", row_header=flag_name_column)]
        return {"body": {"self_ref": "#/body", "children": [{"$ref": "#/tables/0"}]}, "texts": [], "groups": [],
                "tables": [{"self_ref": "#/tables/0", "label": "table", "children": [], "captions": [],
                            "data": {"num_rows": 2, "num_cols": 2, "table_cells": cells}}]}

    flagged = structure_units(document(True), "d", use_docling_core=False)[0]
    assert (flagged.name_field, flagged.name_field_source, flagged.items[0].name) == ("Room", "row_header", "Garden")
    numbered = structure_units(document(False), "d", use_docling_core=False)[0]
    assert (numbered.name_field, numbered.name_field_source) == ("Room", "second_column")
