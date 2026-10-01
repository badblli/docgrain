"""Executable M2c contract spike: source fidelity before retrieval evaluation."""

import copy
import json
from pathlib import Path

import pytest
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, deterministic_item_id
from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunks

from tests.fixtures.lifecycle import mapped_snapshot
from tests.unit.test_m2b_entities import entity_fixture


def rich_snapshot():
    snapshot, *_ = mapped_snapshot()
    value = snapshot.model_dump(mode="json")
    annotation = value["structure"][-1]["annotation"]

    def node(kind, key, **fields):
        return {"kind": kind, "identity_key": key,
                "id": deterministic_item_id(snapshot.document_id, kind, key, policy_version="0.2.0"),
                "annotation": copy.deepcopy(annotation), "field_annotations": {}, **fields}

    first = node("text_block", "first", text="First paragraph.", role="paragraph")
    second = node("text_block", "second", text="Second paragraph.", role="paragraph")
    item = node("text_block", "list-item", text="List entry", role="paragraph")
    lst = node("list", "list", ordered=True, children=[item["id"]])
    rows = []
    for row_index, values in enumerate((("Name", "Count"), ("A", 2), ("B", 3))):
        cells = []
        for column, cell_value in enumerate(values):
            evidence_id = f"cell-{row_index}-{column}"
            value["evidence"].append({"id": evidence_id, "source_version_id": snapshot.source_version.id,
                                      "locator": {"kind": "spreadsheet_range", "sheet": "Data",
                                                  "a1_range": f"{'AB'[column]}{row_index + 1}"}, "note": None})
            cell_annotation = copy.deepcopy(annotation)
            cell_annotation["provenance"]["evidence_ids"] = [evidence_id]
            cells.append({"value": cell_value, "annotation": cell_annotation,
                          "formula": "=1+1" if row_index == 1 and column == 1 else None,
                          "cached_value": 2 if row_index == 1 and column == 1 else None,
                          "display_text": str(cell_value), "row_span": 1, "col_span": 1})
        rows.append(cells)
    table = node("table", "table", caption="Counts", rows=rows)
    chart = node("chart", "chart", artifact_id=None, description=None)
    a = node("section", "section-a", heading="Alpha", level=1,
             children=[first["id"], second["id"], lst["id"], table["id"], chart["id"]])
    third = node("text_block", "third", text="Third paragraph.", role="paragraph")
    b = node("section", "section-b", heading="Beta", level=1, children=[third["id"]])
    root = value["structure"][0]
    root["title"] = "Synthetic contract"
    root["children"] = [a["id"], b["id"]]
    value["structure"] = [root, a, first, second, lst, item, table, chart, b, third]
    return CanonicalKnowledgeSnapshot.model_validate(value)


def test_actual_chunks_are_deterministic_and_leave_canonical_unchanged():
    snapshot, *_ = mapped_snapshot()
    original = snapshot.model_dump(mode="json")
    first = derive_chunks(snapshot, ChunkingSpec())
    assert first == derive_chunks(snapshot, ChunkingSpec())
    assert first.schema_version == "0.3.0"
    assert first.chunks[0].text == "Hello"
    assert first.chunks[0].sources[0].evidence_ids == snapshot.structure[-1].annotation.provenance.evidence_ids
    assert snapshot.model_dump(mode="json") == original


def test_child_order_context_section_and_list_boundaries():
    snapshot = rich_snapshot()
    result = derive_chunks(snapshot, ChunkingSpec(max_chars=2000))
    assert [c.kind for c in result.chunks] == ["text", "text", "table", "text"]
    assert result.chunks[0].text == "First paragraph.\n\nSecond paragraph."
    assert [c.kind for c in result.chunks[1].context] == ["document", "section", "list"]
    assert result.chunks[-1].context[-1].text == "Beta"
    assert all("Beta" not in c.retrieval_text for c in result.chunks[:-1])
    reordered = snapshot.model_copy(update={"structure": list(reversed(snapshot.structure))})
    assert derive_chunks(reordered, ChunkingSpec(max_chars=2000)) == result
    assert result.chunk_omissions[0].reason == "no_description"
    lineage = {(edge.upstream.key, edge.downstream.key) for edge in result.edges}
    for chunk in result.chunks:
        assert all((parent.key, chunk.object_ref.key) in lineage for parent in chunk.parents)


@pytest.mark.parametrize("text", ["  hello 😀 world\n日本語. " * 20, "界" * 300])
def test_oversize_text_lossless_unicode_source_slices(text):
    snapshot, *_ = mapped_snapshot()
    value = snapshot.model_dump(mode="json")
    value["structure"][0]["title"] = None
    value["structure"][-1]["text"] = text
    snapshot = CanonicalKnowledgeSnapshot.model_validate(value)
    result = derive_chunks(snapshot, ChunkingSpec(max_chars=64))
    assert "".join(chunk.text for chunk in result.chunks) == text
    assert all(chunk.character_count <= 64 and not chunk.oversized and chunk.split_fallback for chunk in result.chunks)
    previous = 0
    for chunk in result.chunks:
        source = chunk.sources[0]
        assert source.start == previous and text[source.start:source.end] == chunk.text
        previous = source.end
    assert previous == len(text)


def test_table_rows_explicit_headers_cells_and_atomic_overflow():
    snapshot = rich_snapshot()
    table = next(node for node in snapshot.structure if node.kind == "table")
    spec = ChunkingSpec(max_chars=64, max_table_rows=1, table_header_rows={table.id: 1})
    chunks = [chunk for chunk in derive_chunks(snapshot, spec).chunks if chunk.kind == "table"]
    assert len(chunks) == 2 and all(chunk.oversized for chunk in chunks)
    for index, chunk in enumerate(chunks, start=1):
        payload = json.loads(chunk.text)
        assert payload["caption"] == "Counts" and payload["header_rows"][0][0]["value"] == "Name"
        assert payload["rows"][0][0]["value"] == "AB"[index - 1]
        assert [(s.start, s.end) for s in chunk.sources] == [(0, 1), (index, index + 1)]
        assert {"cell-0-0", "cell-0-1", f"cell-{index}-0", f"cell-{index}-1"} <= set(chunk.evidence_ids)
    assert json.loads(chunks[0].text)["rows"][0][1]["formula"] == "=1+1"
    assert json.loads(chunks[0].text)["rows"][0][1]["cached_value"] == 2
    default = next(c for c in derive_chunks(snapshot, ChunkingSpec()).chunks if c.kind == "table")
    assert json.loads(default.text)["header_rows"] == []
    with pytest.raises(ValueError, match="table header rows"):
        derive_chunks(snapshot, ChunkingSpec(table_header_rows={table.id: 99}))


def test_entity_acceptance_complete_json_and_explicit_omissions():
    from docgrain_domain.canonical.entities import review_entity

    from tests.fixtures.entities import decision, registered_schema

    snapshot, *_ = mapped_snapshot()
    entity = entity_fixture({"name": "A" * 200, "capacity": 2})
    value = snapshot.model_dump(mode="json")
    value["schema_version"] = "0.4.0"
    spec = snapshot.knowledge_revision.processing.model_copy(update={"schema_version": "0.4.0"})
    from docgrain_domain.canonical import processing_revision_id
    value["knowledge_revision"]["processing"] = spec.model_dump(mode="json")
    value["knowledge_revision"]["id"] = processing_revision_id(snapshot.source_version.id, spec)
    for producer in value["knowledge_revision"]["producers"]:
        producer["configuration_digest"] = spec.digest
    value["knowledge_revision"]["producers"].append({"id": "producer-entity", "name": "fixture", "version": "1", "configuration_digest": spec.digest})
    # Fixture annotations name their explicit extraction producer.
    value["knowledge_revision"]["producers"][-1]["id"] = entity.annotation.provenance.producer_id
    value["domain_schemas"] = [registered_schema().reference.model_dump(mode="json")]
    value["entities"] = [entity.model_dump(mode="json")]
    pending = CanonicalKnowledgeSnapshot.model_validate(value)
    result = derive_chunks(pending, ChunkingSpec(max_chars=64))
    assert not any(c.kind == "entity" for c in result.chunks)
    assert result.chunk_omissions[-1].reason == "unaccepted_entity"
    accepted = review_entity(review_entity(entity, decision("extracted", "needs_review")), decision("needs_review", "accepted"))
    value["entities"] = [accepted.model_dump(mode="json")]
    snapshot = CanonicalKnowledgeSnapshot.model_validate(value)
    chunk = next(c for c in derive_chunks(snapshot, ChunkingSpec(max_chars=64)).chunks if c.kind == "entity")
    assert json.loads(chunk.text) == accepted.data and chunk.oversized and not chunk.split_fallback
    assert chunk.sources[0].field_pointers == ["/capacity", "/name"]
    assert derive_chunks(snapshot, ChunkingSpec(include_entities=False)).chunk_omissions[-1].reason == "entity_disabled"


def test_context_content_config_identity_and_payload_tamper():
    snapshot = rich_snapshot()
    first = derive_chunks(snapshot, ChunkingSpec())
    changed = derive_chunks(snapshot, ChunkingSpec(max_chars=2000))
    assert changed.revision.id != first.revision.id
    assert changed.chunks[0].object_ref.object_id != first.chunks[0].object_ref.object_id
    value = snapshot.model_dump(mode="json")
    value["structure"][1]["heading"] = "Changed heading"
    renamed = derive_chunks(CanonicalKnowledgeSnapshot.model_validate(value), ChunkingSpec())
    assert renamed.chunks[0].object_ref.object_id != first.chunks[0].object_ref.object_id
    assert renamed.chunks[-1].object_ref.object_id == first.chunks[-1].object_ref.object_id
    from docgrain_domain.canonical.lineage import DerivedManifest
    malformed = first.model_dump(mode="json")
    malformed["chunks"][0]["retrieval_text"] = "forged"
    with pytest.raises(ValueError, match="contextualized text"):
        DerivedManifest.model_validate(malformed)


def test_empty_content_and_versioned_schema_parity():
    snapshot, *_ = mapped_snapshot()
    value = snapshot.model_dump(mode="json")
    value["structure"][-1]["text"] = ""
    with pytest.raises(ValueError, match="no extractable"):
        derive_chunks(CanonicalKnowledgeSnapshot.model_validate(value), ChunkingSpec())
    from docgrain_domain.canonical.schema import generated_lineage_schema_text
    from jsonschema import Draft202012Validator
    root = Path(__file__).resolve().parents[2] / "packages/domain/docgrain_domain/canonical/schemas"
    for version in ("0.1.0", "0.2.0", "0.3.0"):
        document = generated_lineage_schema_text(version)
        assert document == (root / f"derived-manifest-{version}.schema.json").read_text(encoding="utf-8")
        Draft202012Validator.check_schema(json.loads(document))
    Draft202012Validator(json.loads(generated_lineage_schema_text("0.3.0"))).validate(
        derive_chunks(snapshot, ChunkingSpec()).model_dump(mode="json"))


def test_chunk_api_demo_and_missing_records(monkeypatch):
    from docgrain_api.main import app
    from docgrain_api.settings import get_settings
    from fastapi.testclient import TestClient
    monkeypatch.setattr(get_settings(), "use_fixtures", True)
    client = TestClient(app)
    assert client.post("/v1/knowledge/revisions/missing/chunks", json={}).status_code == 409
    assert client.get("/v1/knowledge/revisions/missing/chunks?chunk_revision_id=missing").status_code == 404
    assert client.get("/v1/knowledge/derivations/missing/chunks/missing").status_code == 404
