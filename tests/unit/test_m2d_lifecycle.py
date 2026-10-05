"""M2d executable contract spike; vectors below are an explicit test adapter."""

import copy

import pytest
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.chunking import ChunkingSpec
from docgrain_domain.canonical.incremental import canonical_diff, plan_chunks

from tests.fixtures.incremental import index_spec, revised
from tests.unit.test_m2c_chunking import rich_snapshot


def test_heading_change_rebuilds_only_dependent_chunks_and_deletion_is_explicit():
    old = rich_snapshot()
    value = copy.deepcopy(old.model_dump(mode="json"))
    section = next(n for n in value["structure"] if n.get("heading") == "Alpha")
    section["heading"] = "Updated Alpha"
    new = CanonicalKnowledgeSnapshot.model_validate(value)
    diff = canonical_diff(old, new)
    assert [c.object_id for c in diff.changes] == [section["id"]]
    plan = plan_chunks(old, new, ChunkingSpec(max_chars=2000))
    assert len(plan.reuse) == 1 and len(plan.embed) == 3 and len(plan.delete) == 3


def test_cell_change_prunes_unchanged_rows_but_header_changes_all_row_chunks():
    old = rich_snapshot()
    table = next(n for n in old.structure if n.kind == "table")
    spec = ChunkingSpec(max_chars=2000, max_table_rows=1, table_header_rows={table.id: 1})
    def mutate(value):
        node = next(n for n in value["structure"] if n["id"] == table.id)
        node["rows"][1][1]["value"] = 9
    changed = revised(old, mutate)
    diff = canonical_diff(old, changed)
    assert diff.changes[0].content_paths == ["/rows/1/1/value"]
    plan = plan_chunks(old, changed, spec)
    assert len(plan.embed) == 1 and len(plan.reuse) == 4 and len(plan.delete) == 1
    def header(value):
        next(n for n in value["structure"] if n["id"] == table.id)["rows"][0][0]["value"] = "Updated header"
    assert len(plan_chunks(old, revised(old, header), spec).embed) == 2


def test_evidence_only_change_refreshes_occurrences_without_embedding():
    old = rich_snapshot()
    new = revised(old, lambda v: v["evidence"][0].update(note="Corrected evidence"))
    diff = canonical_diff(old, new)
    assert diff.changes and all(not c.content_paths for c in diff.changes)
    assert any("/evidence" in c.metadata_paths for c in diff.changes)
    plan = plan_chunks(old, new, ChunkingSpec())
    assert not plan.embed and not plan.delete and len(plan.metadata_refresh) == len(plan.reuse) == 4


def test_removed_node_and_empty_result_leave_no_fake_chunks():
    from docgrain_domain.canonical.chunking import derive_chunk_set, derive_chunks
    old = rich_snapshot()
    def empty(value):
        value["structure"] = [value["structure"][0]]
        value["structure"][0]["children"] = []
    new = revised(old, empty)
    result = derive_chunk_set(new, ChunkingSpec())
    assert result.chunks == []
    with pytest.raises(ValueError, match="no extractable"):
        derive_chunks(new, ChunkingSpec())
    plan = plan_chunks(old, new, ChunkingSpec())
    assert len(plan.delete) == 4 and not plan.embed and not plan.reuse


def test_lineage_walk_has_no_default_trace_cap_and_validates_scope():
    from docgrain_domain.canonical.chunking import derive_chunks
    from docgrain_domain.canonical.incremental import invalidated_descendants
    from docgrain_domain.canonical.lineage import LineageGraph
    old = rich_snapshot()
    graph = LineageGraph(old)
    graph.extend(derive_chunks(old, ChunkingSpec(max_chars=64)))
    new = revised(old, lambda v: v["structure"][0].update(title="New title"))
    result = invalidated_descendants(canonical_diff(old, new), graph)
    assert len([obj for obj in result if obj.kind == "chunk"]) == len(derive_chunks(old, ChunkingSpec(max_chars=64)).chunks)
    with pytest.raises(ValueError, match="scope"):
        invalidated_descendants(canonical_diff(new, old), graph)


@pytest.mark.parametrize("vector", [[1], [1, float("nan")], [float("inf"), 1], [True, 1], ["1", 1]])
def test_provider_vector_validation(vector):
    with pytest.raises(ValueError, match="finite"):
        index_spec().embedding.validate_vector(vector)


def test_configuration_and_workspace_cache_isolation():
    from docgrain_domain.canonical.indexing import embedding_cache_key
    spec = index_spec().embedding
    checksum = "a" * 64
    first = embedding_cache_key("w1", "d1", spec, checksum)
    assert first != embedding_cache_key("w2", "d1", spec, checksum)
    assert first != embedding_cache_key("w1", "d2", spec, checksum)
    assert first != embedding_cache_key("w1", "d1", spec.model_copy(update={"version": "2"}), checksum)


def test_index_schema_and_demo_never_fabricate_results(monkeypatch):
    import json
    from pathlib import Path

    from docgrain_api.main import app
    from docgrain_api.settings import get_settings
    from docgrain_domain.canonical.schema import generated_index_schema_text
    from fastapi.testclient import TestClient
    from jsonschema import Draft202012Validator

    text = generated_index_schema_text()
    path = Path(__file__).resolve().parents[2] / "packages/domain/docgrain_domain/canonical/schemas/index-generation-0.1.0.schema.json"
    assert text == path.read_text(encoding="utf-8")
    Draft202012Validator.check_schema(json.loads(text))
    monkeypatch.setattr(get_settings(), "use_fixtures", True)
    client = TestClient(app)
    assert client.post("/v1/knowledge/revisions/missing/diff", json={"from_revision_id": "missing"}).status_code == 404
    assert client.get("/v1/knowledge/documents/missing/indexes/default?workspace_id=missing").status_code == 404
