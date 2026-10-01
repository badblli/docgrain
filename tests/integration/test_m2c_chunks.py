"""Stored canonical chunks with real PostgreSQL, HTTP and opt-in real parsers."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from docgrain_api.canonical_repository import CanonicalConflict
from docgrain_api.main import app
from docgrain_api.routers import canonical_chunks as chunk_routes
from docgrain_api.settings import get_settings
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunks
from docgrain_domain.canonical.lineage import DerivedManifest, ObjectRef
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.canonical_writer import persist_structural
from docgrain_worker.structural import DocumentParser, VerifiedSource
from fastapi.testclient import TestClient

from tests.fixtures.lifecycle import derived_chain, mapped_snapshot
from tests.integration import test_m2a_repository as m2a_fixtures
from tests.integration.test_m2b_repository import accepted

lifecycle_store = m2a_fixtures.lifecycle_store
real_corpus = m2a_fixtures.real_corpus


def seed(repository):
    _, parsed, source, spec = mapped_snapshot()
    snapshot, _ = persist_structural(repository, parsed, source, spec=spec)
    return snapshot


def test_publication_replay_concurrency_versions_and_bidirectional_lineage(lifecycle_store):
    repository, _, _ = lifecycle_store
    snapshot = seed(repository)
    manifest = derive_chunks(snapshot, ChunkingSpec())
    before = snapshot.model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: repository.append_derived(manifest), range(2))) == [False, True]
    assert repository.get_derivation(manifest.revision.id) == manifest
    other = derive_chunks(snapshot, ChunkingSpec(max_chars=100))
    assert repository.append_derived(other)
    assert repository.get_heads(snapshot.document_id) == (snapshot.knowledge_revision.id, None)
    assert repository.get_snapshot(snapshot.knowledge_revision.id).model_dump(mode="json") == before
    graph = repository.get_lineage(snapshot.knowledge_revision.id)
    chunk = manifest.chunks[0]
    upstream = graph.trace(chunk.object_ref, "upstream")
    assert {obj.kind for obj in upstream.objects} == {"source", "processing", "canonical", "chunk"}
    assert chunk.object_ref in graph.trace(chunk.sources[0].object_ref, "downstream").objects


def test_forged_payload_evidence_identity_and_workspace_rejected(lifecycle_store):
    repository, _, _ = lifecycle_store
    snapshot = seed(repository)
    manifest = derive_chunks(snapshot, ChunkingSpec())
    forged = manifest.model_dump(mode="json")
    chunk = forged["chunks"][0]
    chunk["text"] = "fabricated data"
    from docgrain_domain.canonical.lineage import contextualize_chunk
    chunk["retrieval_text"] = contextualize_chunk(chunk["text"], manifest.chunks[0].context)
    chunk["content_sha256"] = hashlib.sha256(chunk["retrieval_text"].encode()).hexdigest()
    chunk["character_count"] = len(chunk["retrieval_text"])
    with pytest.raises(CanonicalConflict, match="strategy derivation"):
        repository.append_derived(DerivedManifest.model_validate(forged))
    forged = manifest.model_dump(mode="json")
    forged["chunks"][0]["sources"][0]["evidence_ids"] = ["other-workspace-evidence"]
    forged["chunks"][0]["evidence_ids"].append("other-workspace-evidence")
    # Keep the model's evidence union internally consistent; storage still verifies against source.
    forged["chunks"][0]["evidence_ids"] = list(dict.fromkeys(
        ref for item in [*forged["chunks"][0]["context"], *forged["chunks"][0]["sources"]] for ref in item["evidence_ids"]))
    with pytest.raises(CanonicalConflict, match="strategy derivation"):
        repository.append_derived(DerivedManifest.model_validate(forged))
    from docgrain_domain.canonical.lifecycle import DerivedRevision
    values = manifest.revision.model_dump(exclude={"id"})
    values["workspace_id"] = "other-workspace"
    wrong = DerivedRevision.create(**values)
    forged = manifest.model_dump(mode="json")
    forged["revision"] = wrong.model_dump(mode="json")
    for obj in forged["objects"]:
        obj["revision_id"] = wrong.id
    for item in forged["chunks"]:
        item["object_ref"]["revision_id"] = wrong.id
    for edge in forged["edges"]:
        edge["downstream"]["revision_id"] = wrong.id
    with pytest.raises(CanonicalConflict, match="workspace scope"):
        repository.append_derived(DerivedManifest.model_validate(forged))
    assert repository.get_derivation(manifest.revision.id) is None


def test_accepted_entity_json_and_evidence_stay_independent_of_chunks(lifecycle_store):
    repository, _, _ = lifecycle_store
    _base, _extracted, _pending, snapshot = accepted(repository)
    manifest = derive_chunks(snapshot, ChunkingSpec())
    assert repository.append_derived(manifest)
    entity = snapshot.entities[0]
    chunk = next(chunk for chunk in manifest.chunks if chunk.kind == "entity")
    assert json.loads(chunk.text) == entity.data
    assert chunk.sources[0].field_pointers == sorted(entity.field_annotations)
    upstream = repository.get_lineage(snapshot.knowledge_revision.id).trace(chunk.object_ref, "upstream")
    assert ObjectRef(kind="canonical", object_id=entity.id, revision_id=snapshot.knowledge_revision.id) in upstream.objects
    assert repository.get_snapshot(snapshot.knowledge_revision.id).entities[0] == entity


def test_http_publish_read_scope_missing_and_legacy_manifest(lifecycle_store, monkeypatch):
    repository, _, _ = lifecycle_store
    snapshot = seed(repository)
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(chunk_routes, "lifecycle_repository", lambda: repository)
    client = TestClient(app)
    path = f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}/chunks"
    assert client.post("/v1/knowledge/revisions/missing/chunks", json={}).status_code == 404
    assert client.post(path, json={"strategy_version": "99"}).status_code == 422
    response = client.post(path, json={})
    assert response.status_code == 200 and response.json()["inserted"]
    manifest = DerivedManifest.model_validate(response.json()["manifest"])
    assert client.post(path, json={}).json()["inserted"] is False
    read = client.get(path, params={"chunk_revision_id": manifest.revision.id})
    assert read.status_code == 200 and DerivedManifest.model_validate(read.json()) == manifest
    chunk = manifest.chunks[0].object_ref
    assert client.get(f"/v1/knowledge/derivations/{manifest.revision.id}/chunks/{chunk.object_id}").status_code == 200
    assert client.get(f"/v1/knowledge/derivations/{manifest.revision.id}/chunks/missing").status_code == 404
    assert client.get(path, params={"chunk_revision_id": "missing"}).status_code == 404
    _, chain = derived_chain(snapshot)
    repository.append_derived(chain[0])
    assert client.get(path, params={"chunk_revision_id": chain[0].revision.id}).status_code == 404
    # The same document can have another canonical revision; its chunk set cannot be read via this path.
    _, parsed, source, spec = mapped_snapshot(mapper_version="next")
    newer, _ = persist_structural(repository, parsed, source, spec=spec,
                                 expected_latest_revision_id=snapshot.knowledge_revision.id)
    newer_path = f"/v1/knowledge/revisions/{newer.knowledge_revision.id}/chunks"
    assert client.get(newer_path, params={"chunk_revision_id": manifest.revision.id}).status_code == 404


@pytest.mark.parametrize("name,fmt", [("basic", SourceFormat.PDF), ("docx-headings", SourceFormat.DOCX),
                                      ("txt-multilingual", SourceFormat.TXT), ("xlsx", SourceFormat.XLSX)])
def test_real_parser_structural_chunks_replay_and_source_fidelity(lifecycle_store, real_corpus, name, fmt):
    if fmt is not SourceFormat.TXT:
        pytest.importorskip("docling")
    repository, _, _ = lifecycle_store
    path = real_corpus[name]
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    parsed = DocumentParser().parse(VerifiedSource(path, digest, len(raw)), fmt)
    for item in parsed.items:
        if item.asset_bytes:
            item.asset_path = "fixture://asset/" + hashlib.sha256(item.asset_bytes).hexdigest()
    source = SourceVersion(id="pending", document_id="document-test", workspace_id="workspace-test",
                           content_sha256=digest, storage_uri="fixture://source", storage_version="v1",
                           byte_size=len(raw), mime_type="application/test", filename=path.name,
                           recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    snapshot, _ = persist_structural(repository, parsed, source, pdf_path=path if fmt is SourceFormat.PDF else None)
    original = snapshot.model_dump(mode="json")
    manifest = derive_chunks(snapshot, ChunkingSpec(max_chars=600, max_table_rows=2))
    assert manifest == derive_chunks(snapshot, ChunkingSpec(max_chars=600, max_table_rows=2))
    assert repository.append_derived(manifest)
    assert not repository.append_derived(manifest)
    assert repository.get_snapshot(snapshot.knowledge_revision.id).model_dump(mode="json") == original
    evidence = {e.id for e in snapshot.evidence}
    assert all(set(chunk.evidence_ids) <= evidence for chunk in manifest.chunks)
    nodes = {node.id: node for node in snapshot.structure}
    for chunk in manifest.chunks:
        if chunk.kind == "text":
            assert chunk.text == "\n\n".join(nodes[s.object_ref.object_id].text[s.start:s.end] for s in chunk.sources)
        elif chunk.kind == "table":
            projected = json.loads(chunk.text)
            source_rows = [row for s in chunk.sources for row in nodes[s.object_ref.object_id].rows[s.start:s.end]]
            assert [cell["value"] for row in projected["rows"] for cell in row] == [cell.value for row in source_rows for cell in row]
