import json
from pathlib import Path

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.ai_output import (
    MIME,
    AIOutput,
    context_projection,
    output_bundle,
    readable,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "canonical" / "generic-pdf.json"


def context_snapshot():
    snapshot = CanonicalKnowledgeSnapshot.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    value = output_bundle(snapshot)[0].model_dump(mode="json")
    root, section, paragraph, table = value["content"]
    paragraph["text"] = "A source paragraph with every word intact."
    cell = table["rows"][0][0]

    def new_node(kind, name, **fields):
        return {"id": name, "identity_key": name, "kind": kind,
                "annotation": paragraph["annotation"], "field_annotations": {}, **fields}

    table["rows"] = [
        [{**cell, "value": "Name", "col_span": 2}, {**cell, "value": None,
         "source_attributes": {"merge_covered": True}}, {**cell, "value": "Total"}],
        [{**cell, "value": "Suite | Sea"}, {**cell, "value": 12, "display_text": "12 rooms"},
         {**cell, "value": None, "formula": "=B2*2", "cached_value": 24}],
    ]
    empty = new_node("table", "empty-table", caption=None, rows=[])
    described = new_node("asset", "described-asset", artifact_id="asset-1", description="Pool view")
    undescribed = new_node("asset", "undescribed-asset", artifact_id="asset-2", description=None)
    chart = new_node("chart", "chart-1", artifact_id=None, description="Room count",
                     source_data={"series": [{"title": "Rooms", "cat": {"cells": [{"value": "Suite"}]},
                                               "val": {"cells": [{"value": 12}]}}]})
    item = new_node("text_block", "list-item", text="Listed source fact", role="paragraph")
    listing = new_node("list", "list-1", ordered=False, children=[item["id"]])
    section["children"].extend([listing["id"], empty["id"], described["id"], undescribed["id"], chart["id"]])
    value["content"] = [root, section, paragraph, listing, item, table, empty, described, undescribed, chart]
    return AIOutput.model_validate(value)


def test_context_bundle_format_and_existing_bytes():
    snapshot = CanonicalKnowledgeSnapshot.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    output, _, _, files = output_bundle(snapshot)
    synthetic = context_snapshot()
    context = files["context.md"].decode()
    assert MIME["context.md"] == "text/markdown"
    assert files["canonical.md"] == readable(output).encode()
    assert context == context_projection(output)
    context = context_projection(synthetic)
    assert context == context_projection(synthetic)
    manifest = json.loads(files["manifest.json"])
    assert next(item for item in manifest["files"] if item["name"] == "context.md")["mime_type"] == "text/markdown"
    assert "Suite \\| Sea" in context
    assert "12 rooms" in context and "24 (=B2*2)" in context
    assert "| Name |  | Total |" in context
    assert "[Boş tablo]" in context
    assert "[Görsel: Pool view]" in context and "[Görsel: açıklama yok]" in context
    assert "| Rooms | Suite | 12 |" in context
    assert "- Listed source fact" in context
    assert context.count("[§") == len(synthetic.content)
    assert all(f"§{index} → {node.id}" in context for index, node in enumerate(synthetic.content, 1))
    body, key_map = context.split("## Kaynak anahtarları", 1)
    assert all(node.id not in body for node in synthetic.content)
    assert all(f"§{index} → {node.id}" in key_map for index, node in enumerate(synthetic.content, 1))
    assert "[§1 p.1]" in context


def test_context_contains_every_text_and_nonempty_table_value():
    output = context_snapshot()
    context = context_projection(output)
    for node in output.content:
        if node.kind == "text_block" and node.text:
            assert node.text in context
        if node.kind == "table":
            for row in node.rows:
                for cell in row:
                    if cell.value is not None and cell.value != "":
                        assert (str(cell.value).replace("|", "\\|") in context
                                or (cell.display_text is not None and cell.display_text in context))


def test_no_header_vertical_merge_and_formula_without_cached_value():
    output = context_snapshot()
    value = output.model_dump(mode="json")
    table = next(node for node in value["content"] if node["kind"] == "table" and node["rows"])
    cell = table["rows"][0][0]
    table["rows"] = [
        [{**cell, "value": 10, "row_span": 2, "col_span": 1}, {**cell, "value": "A"}],
        [{**cell, "value": None}, {**cell, "value": None, "formula": "=A1*2"}],
    ]
    context = context_projection(AIOutput.model_validate(value))
    assert "| 1 | 2 |" in context
    assert "| 10 | A |" in context
    assert "|  | (=A1*2) |" in context
