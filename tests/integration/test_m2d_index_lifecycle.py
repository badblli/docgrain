"""Real PostgreSQL publication, checkpointed retries, CAS and real parser updates."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import psycopg
import pytest
from docgrain_api.canonical_repository import CanonicalConflict
from docgrain_api.index_repository import IndexRepository
from docgrain_api.main import app
from docgrain_api.routers import incremental as routes
from docgrain_api.settings import get_settings
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.chunking import ChunkingSpec
from docgrain_domain.canonical.incremental import (
    canonical_diff,
    invalidated_descendants,
)
from docgrain_domain.canonical.indexing import IndexGeneration
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.canonical_writer import persist_structural
from docgrain_worker.index_lifecycle import refresh_index
from docgrain_worker.structural import DocumentParser, VerifiedSource
from fastapi.testclient import TestClient
from psycopg import sql

from tests.fixtures.incremental import FixtureEmbedder, index_spec, revised
from tests.integration import test_m2a_repository as m2a_fixtures
from tests.integration.test_m2b_repository import accepted
from tests.unit.test_m2c_chunking import rich_snapshot

lifecycle_store = m2a_fixtures.lifecycle_store
real_corpus = m2a_fixtures.real_corpus


@pytest.fixture
def store(lifecycle_store):
    _repository, connect, schema = lifecycle_store
    return IndexRepository(connect, schema), connect, schema


def seed(repository):
    snapshot = rich_snapshot()
    repository.append(snapshot, expected_latest_revision_id=None)
    return snapshot


def build(repository, snapshot, embedder=None, *, base=None, full=False, spec=None):
    return refresh_index(repository, snapshot.knowledge_revision.id, spec or index_spec(), embedder or FixtureEmbedder(),
                         expected_generation_id=base, full=full)


def test_selective_cell_change_deletions_occurrence_refresh_and_full_rebuild(store):
    repository, _, _ = store
    snapshot = seed(repository)
    spec = index_spec(chunking=ChunkingSpec(max_chars=2000, max_table_rows=1))
    provider = FixtureEmbedder()
    first, inserted = build(repository, snapshot, provider, spec=spec)
    assert inserted and len(provider.calls) == len(first.entries) == 6
    def mutate(v):
        next(n for n in v["structure"] if n["kind"] == "table")["rows"][1][1]["value"] = 9
        # Delete Beta's body but retain its container with no heading/body.
        section = next(n for n in v["structure"] if n.get("heading") == "Beta")
        removed = set(section["children"])
        section["children"] = []
        section["heading"] = ""
        v["structure"] = [n for n in v["structure"] if n["id"] not in removed]
    newer = revised(snapshot, mutate)
    repository.append(newer, expected_latest_revision_id=snapshot.knowledge_revision.id)
    provider = FixtureEmbedder()
    second, _ = build(repository, newer, provider, base=first.revision.id, spec=spec)
    assert len(provider.calls) == 1 and len(second.reused_chunk_ids) == 4 and len(second.removed_chunk_ids) == 2
    assert len(second.entries) == 5 and repository.get_active("workspace-test", "document-test") == second
    assert repository.get_generation(first.revision.id) == first
    assert all(p.revision_id == newer.knowledge_revision.id for entry in second.entries for p in entry.chunk.parents)
    graph = repository.get_lineage(snapshot.knowledge_revision.id)
    candidates = invalidated_descendants(canonical_diff(snapshot, newer), graph)
    assert {"canonical", "chunk", "embedding", "index"} <= {ref.kind for ref in candidates}
    provider = FixtureEmbedder()
    rebuilt, _ = build(repository, newer, provider, base=second.revision.id, spec=spec, full=True)
    assert len(provider.calls) == 5 and not rebuilt.reused_chunk_ids
    assert [(e.chunk, e.vector) for e in rebuilt.entries] == [(e.chunk, e.vector) for e in second.entries]
    # Retrying an old successful operation does not roll back a newer active head.
    assert not build(repository, snapshot, FixtureEmbedder(fail_at=1), spec=spec)[1]
    assert repository.get_active("workspace-test", "document-test") == rebuilt


def test_partial_provider_failure_checkpoints_and_retry_preserves_old_head(store):
    repository, _, _ = store
    old = seed(repository)
    first, _ = build(repository, old)
    new = revised(old, lambda v: v["structure"][0].update(title="Changed context"))
    repository.append(new, expected_latest_revision_id=old.knowledge_revision.id)
    provider = FixtureEmbedder(fail_at=2)
    with pytest.raises(RuntimeError, match="provider failure"):
        build(repository, new, provider, base=first.revision.id)
    assert repository.get_active("workspace-test", "document-test") == first
    provider = FixtureEmbedder()
    second, _ = build(repository, new, provider, base=first.revision.id)
    assert len(provider.calls) == 3 and len(second.reused_chunk_ids) == 1
    assert not build(repository, new, FixtureEmbedder(fail_at=1), base=first.revision.id)[1]


def test_sql_failure_rolls_back_generation_and_head_but_keeps_checkpoints(store):
    repository, connect, schema = store
    old = seed(repository)
    first, _ = build(repository, old)
    new = revised(old, lambda v: v["structure"][0].update(title="SQL failure target"))
    repository.append(new, expected_latest_revision_id=old.knowledge_revision.id)
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("""CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$
                                BEGIN RAISE EXCEPTION 'injected publication failure'; END $$""")
                       .format(sql.Identifier(schema, "fail_index_head")))
        cursor.execute(sql.SQL("CREATE TRIGGER injected_failure BEFORE UPDATE ON {} FOR EACH ROW EXECUTE FUNCTION {}()")
                       .format(sql.Identifier(schema, "document_index_heads"), sql.Identifier(schema, "fail_index_head")))
    with pytest.raises(psycopg.errors.RaiseException, match="publication failure"):
        build(repository, new, base=first.revision.id)
    assert repository.get_active("workspace-test", "document-test") == first
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(schema, "index_generations")))
        assert cursor.fetchone()[0] == 1
        cursor.execute(sql.SQL("DROP TRIGGER injected_failure ON {}").format(sql.Identifier(schema, "document_index_heads")))
    provider = FixtureEmbedder(fail_at=1)
    second, _ = build(repository, new, provider, base=first.revision.id)
    assert not provider.calls and len(second.reused_chunk_ids) == 4


def test_concurrent_duplicate_builds_embed_once_stale_target_and_cas(store):
    repository, _, _ = store
    old = seed(repository)
    provider = FixtureEmbedder()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: build(repository, old, provider), range(2)))
    assert sorted(inserted for _, inserted in results) == [False, True] and len(provider.calls) == 4
    first = results[0][0]
    newer = revised(old, lambda v: v["structure"][0].update(title="Newer"))
    repository.append(newer, expected_latest_revision_id=old.knowledge_revision.id)
    with pytest.raises(CanonicalConflict, match="no longer latest"):
        build(repository, old, base=first.revision.id, full=True)
    with pytest.raises(CanonicalConflict, match="head changed"):
        build(repository, newer, base=None)
    assert repository.get_active("workspace-test", "document-test") == first


def test_readers_keep_old_generation_during_build_and_stale_publication_is_rejected(store):
    repository, _, _ = store
    old = seed(repository)
    first, _ = build(repository, old)
    new = revised(old, lambda v: v["structure"][0].update(title="Building"))
    repository.append(new, expected_latest_revision_id=old.knowledge_revision.id)
    entered, release = Event(), Event()
    class PausedEmbedder(FixtureEmbedder):
        def embed(self, text, spec):
            entered.set()
            assert release.wait(timeout=10)
            return super().embed(text, spec)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(build, repository, new, PausedEmbedder(), base=first.revision.id)
        try:
            assert entered.wait(timeout=10)
            assert repository.get_active("workspace-test", "document-test") == first
            newest = revised(new, lambda v: v["structure"][0].update(title="Newest"), version="m2d-test-3")
            repository.append(newest, expected_latest_revision_id=new.knowledge_revision.id)
        finally:
            release.set()
        with pytest.raises(CanonicalConflict, match="no longer latest"):
            future.result(timeout=15)
    assert repository.get_active("workspace-test", "document-test") == first
    second, _ = build(repository, newest, base=first.revision.id)
    assert repository.get_active("workspace-test", "document-test") == second


def test_forged_new_payload_vector_and_chunk_rejected_before_head_switch(store):
    repository, _, _ = store
    old = seed(repository)
    first, _ = build(repository, old)
    from docgrain_domain.canonical.indexing import entry_refs, generation_revision
    # Create a different valid operation ID, then forge its vector against checkpointed output.
    value = first.model_dump(mode="json")
    value["base_id"] = first.revision.id
    embedding, indexing = generation_revision(first.chunk_set, first.spec, first.revision.id, False)
    value["revision"] = indexing.model_dump(mode="json")
    for entry in value["entries"]:
        from docgrain_domain.canonical.lineage import ChunkPayload
        refs = entry_refs(ChunkPayload.model_validate(entry["chunk"]), embedding, indexing)
        entry["index_ref"] = refs[1].model_dump(mode="json")
    value["entries"][0]["vector"] = [0.0, 0.0]
    with pytest.raises(CanonicalConflict, match="checkpoint"):
        repository.publish(IndexGeneration.model_validate(value))
    value["entries"][0]["vector"] = first.entries[0].vector
    value["chunk_set"]["chunk_omissions"] = []
    with pytest.raises(CanonicalConflict, match="canonical strategy"):
        repository.publish(IndexGeneration.model_validate(value))
    assert repository.get_active("workspace-test", "document-test") == first


def test_empty_generation_config_change_immutable_payload_and_scoped_reads(store):
    repository, connect, schema = store
    old = seed(repository)
    first, _ = build(repository, old)
    changed_spec = index_spec()
    changed_spec.embedding.version = "2"
    provider = FixtureEmbedder()
    second, _ = build(repository, old, provider, base=first.revision.id, spec=changed_spec)
    assert len(provider.calls) == 4 and not second.reused_chunk_ids
    def empty(v):
        v["structure"] = [v["structure"][0]]
        v["structure"][0]["children"] = []
    new = revised(old, empty)
    repository.append(new, expected_latest_revision_id=old.knowledge_revision.id)
    provider = FixtureEmbedder(fail_at=1)
    cleared, _ = build(repository, new, provider, base=second.revision.id, spec=changed_spec)
    assert not provider.calls and not cleared.entries and len(cleared.removed_chunk_ids) == 4
    assert repository.get_active("workspace-test", "document-test") == cleared
    assert repository.get_active("other", "document-test") is None
    assert repository.get_active("workspace-test", "document-test", "other") is None
    with pytest.raises(psycopg.errors.RaiseException), connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(schema, "index_generations")))
    forged = second.model_dump(mode="json")
    forged["entries"][0]["vector"] = [0, 0]
    with pytest.raises(CanonicalConflict, match="different immutable"):
        repository.publish(IndexGeneration.model_validate(forged))


def test_evidence_only_update_and_entity_removal_reuse_text_vectors(store):
    repository, _, _ = store
    _base, _extracted, _pending, old = accepted(repository)
    first, _ = build(repository, old)
    assert any(e.chunk.kind == "entity" for e in first.entries)
    def remove(v):
        v["entities"] = []
        v["evidence"][0]["note"] = "Corrected provenance"
    new = revised(old, remove)
    repository.append(new, expected_latest_revision_id=old.knowledge_revision.id)
    provider = FixtureEmbedder(fail_at=1)
    second, _ = build(repository, new, provider, base=first.revision.id)
    assert not provider.calls and len(second.removed_chunk_ids) == 1 and len(second.entries) == 1
    assert second.entries[0].chunk.sources[0].object_ref.revision_id == new.knowledge_revision.id
    assert repository.get_snapshot(old.knowledge_revision.id).entities == old.entities


def test_read_only_http_diff_plan_scope_active_and_demo(store, monkeypatch):
    repository, _, _ = store
    old = seed(repository)
    first, _ = build(repository, old)
    new = revised(old, lambda v: v["structure"][1].update(heading="New Alpha"))
    repository.append(new, expected_latest_revision_id=old.knowledge_revision.id)
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(routes, "lifecycle_repository", lambda: repository)
    client = TestClient(app)
    prefix = f"/v1/knowledge/revisions/{new.knowledge_revision.id}"
    body = {"from_revision_id": old.knowledge_revision.id}
    response = client.post(prefix + "/diff", json=body)
    assert response.status_code == 200 and response.json()["invalidated_candidates"]
    response = client.post(prefix + "/index-plan", json=body)
    assert response.status_code == 200 and len(response.json()["embed"]) == 3
    assert client.post(prefix + "/diff", json={"from_revision_id": "missing"}).status_code == 404
    assert client.post(prefix + "/index-plan", json={**body, "chunking": {"max_chars": 0}}).status_code == 422
    path = "/v1/knowledge/documents/document-test/indexes/default"
    assert client.get(path, params={"workspace_id": "workspace-test"}).json()["revision"]["id"] == first.revision.id
    assert client.get(path, params={"workspace_id": "other"}).status_code == 404
    assert repository.get_active("workspace-test", "document-test") == first


@pytest.mark.parametrize("name,fmt", [("txt-multilingual", SourceFormat.TXT), ("xlsx", SourceFormat.XLSX)])
def test_real_source_edit_new_revision_selective_refresh(store, real_corpus, name, fmt):
    if fmt is SourceFormat.XLSX:
        pytest.importorskip("docling")
    repository, _, _ = store
    path = real_corpus[name]
    def parse_and_store(parent=None):
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        parsed = DocumentParser().parse(VerifiedSource(path, checksum, len(raw)), fmt)
        source = SourceVersion(id="pending", workspace_id="workspace-test", document_id="document-test",
                               content_sha256=checksum, storage_uri="fixture://source/" + checksum,
                               storage_version=checksum, byte_size=len(raw), mime_type="application/test",
                               filename=path.name, recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
        return persist_structural(repository, parsed, source, expected_latest_revision_id=parent)[0]
    old = parse_and_store()
    spec = index_spec(chunking=ChunkingSpec(max_chars=64, max_table_rows=1))
    first, _ = build(repository, old, spec=spec)
    if fmt is SourceFormat.TXT:
        path.write_text(path.read_text(encoding="utf-8") + "\nNew paragraph for update.\n", encoding="utf-8")
    else:
        import openpyxl
        workbook = openpyxl.load_workbook(path)
        workbook.active["B2"] = "Changed cell"
        workbook.save(path)
    new = parse_and_store(old.knowledge_revision.id)
    assert old.source_version.id != new.source_version.id
    provider = FixtureEmbedder()
    second, _ = build(repository, new, provider, base=first.revision.id, spec=spec)
    assert canonical_diff(old, new).source_changed and provider.calls
    assert second.reused_chunk_ids and len(provider.calls) < len(second.entries)
    assert all(p.revision_id == new.knowledge_revision.id for e in second.entries for p in e.chunk.parents)
