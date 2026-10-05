"""M2a lifecycle with real PostgreSQL and separately gated real Docling parsing."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import psycopg
import pytest
from docgrain_api.canonical_repository import CanonicalConflict, CanonicalRepository
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.canonical_writer import persist_structural
from docgrain_worker.structural import DocumentParser, VerifiedSource
from psycopg import sql

from tests.fixtures.lifecycle import derived_chain, mapped_snapshot


@pytest.fixture
def lifecycle_store():
    database_url = os.environ.get("DOCGRAIN_M1_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set DOCGRAIN_M1_TEST_DATABASE_URL for isolated PostgreSQL tests")
    schema = "m2a_test_" + uuid.uuid4().hex
    def connect():
        return psycopg.connect(database_url)
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(sql.SQL("CREATE TABLE {} (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL)")
                       .format(sql.Identifier(schema, "documents")))
        cursor.execute(sql.SQL("INSERT INTO {} VALUES ('document-test', 'workspace-test')")
                       .format(sql.Identifier(schema, "documents")))
    repository = CanonicalRepository(connect, schema=schema)
    try:
        repository.initialize()
        yield repository, connect, schema
    finally:
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_reprocess_replay_original_receipt_conflict_and_chronology(lifecycle_store):
    repository, _, _ = lifecycle_store
    _, result, source, spec = mapped_snapshot()
    first, inserted = persist_structural(repository, result, source, spec=spec)
    assert inserted
    replay, inserted = persist_structural(repository, result, source, spec=spec)
    assert not inserted and replay == first
    changed_spec = spec.model_copy(update={"mapper_version": "m2a-2"})
    second, inserted = persist_structural(repository, result, source, spec=changed_spec,
                                         expected_latest_revision_id=first.knowledge_revision.id)
    assert inserted and first.source_version == second.source_version
    assert second.knowledge_revision.parent_revision_id == first.knowledge_revision.id
    assert [n.id for n in first.structure] == [n.id for n in second.structure]
    new_receipt = source.model_copy(update={"storage_uri": "fixture://new-upload", "storage_version": "v2",
                                           "filename": "renamed.txt", "recorded_at": datetime.now(UTC)})
    old_replay, inserted = persist_structural(repository, result, new_receipt, spec=spec,
                                             expected_latest_revision_id=second.knowledge_revision.id)
    assert not inserted and old_replay == first
    assert repository.get_heads(source.document_id) == (second.knowledge_revision.id, None)
    conflicting = copy.deepcopy(result)
    conflicting.items[0].text = "Conflicting output"
    with pytest.raises(CanonicalConflict, match="different immutable snapshot"):
        persist_structural(repository, conflicting, source, spec=spec)
    assert repository.get_heads(source.document_id)[0] == second.knowledge_revision.id


def test_concurrent_duplicate_and_distinct_processing_cas(lifecycle_store):
    repository, _, _ = lifecycle_store
    _, result, source, spec = mapped_snapshot()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: persist_structural(repository, result, source, spec=spec)[1], range(2)))
    assert sorted(results) == [False, True]
    head = repository.get_heads(source.document_id)[0]
    def attempt(version):
        try:
            return persist_structural(repository, result, source,
                                      spec=spec.model_copy(update={"mapper_version": version}),
                                      expected_latest_revision_id=head)[1]
        except CanonicalConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ["m2a-2", "m2a-3"])) == [False, True]


def test_persisted_bidirectional_lineage_idempotency_and_immutable_rows(lifecycle_store):
    repository, connect, schema = lifecycle_store
    _, result, source, spec = mapped_snapshot()
    snapshot, _ = persist_structural(repository, result, source, spec=spec)
    canonical, manifests = derived_chain(snapshot)
    with pytest.raises(ValueError, match="unknown upstream"):
        repository.append_derived(manifests[1])
    for manifest in manifests:
        assert repository.append_derived(manifest)
        assert not repository.append_derived(manifest)
    graph = repository.get_lineage(snapshot.knowledge_revision.id)
    assert {obj.kind for obj in graph.trace(canonical, "downstream").objects} == {
        "canonical", "chunk", "embedding", "index"}
    assert len(graph.trace(manifests[-1].objects[0], "upstream").objects) == 6
    # A conflicting manifest cannot replace the published row, even under the same config.
    value = manifests[0].model_dump(mode="json")
    value["objects"][0]["object_id"] = "different-chunk"
    value["edges"][0]["downstream"]["object_id"] = "different-chunk"
    from docgrain_domain.canonical.lineage import DerivedManifest
    with pytest.raises(CanonicalConflict, match="different immutable payload"):
        repository.append_derived(DerivedManifest.model_validate(value))
    with pytest.raises(psycopg.errors.RaiseException), connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(schema, "derived_revisions")))
    assert repository.get_heads(source.document_id) == (snapshot.knowledge_revision.id, None)


@pytest.fixture(scope="module")
def real_corpus(tmp_path_factory):
    if not os.environ.get("DOCGRAIN_M1_TEST_DATABASE_URL"):
        pytest.skip("real parser publication requires the isolated PostgreSQL test DSN")
    pytest.importorskip("docx", reason="synthetic corpus generation requires python-docx")
    from tests.fixtures.structural.generate import create_corpus
    return create_corpus(tmp_path_factory.mktemp("m2a-real-corpus"))


@pytest.mark.parametrize("name,fmt", [("basic", SourceFormat.PDF), ("docx-headings", SourceFormat.DOCX),
                                      ("txt-multilingual", SourceFormat.TXT), ("xlsx", SourceFormat.XLSX)])
def test_real_formats_reparse_processing_and_lineage(lifecycle_store, real_corpus, name, fmt):
    if fmt is not SourceFormat.TXT and importlib.util.find_spec("docling") is None:
        pytest.skip("real Docling requires the worker image")
    repository, _, _ = lifecycle_store
    path = real_corpus[name]
    data = path.read_bytes()
    verified = VerifiedSource(path, hashlib.sha256(data).hexdigest(), len(data))
    source = SourceVersion(id="pending", document_id="document-test", workspace_id="workspace-test",
                           content_sha256=verified.content_sha256, storage_uri="fixture://immutable-source",
                           storage_version="v1", byte_size=len(data), mime_type=f"application/{fmt.value}",
                           filename=path.name, recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    snapshots = []
    for iteration in range(2):
        parsed = DocumentParser().parse(verified, fmt)
        for item in parsed.items:
            if item.asset_bytes:
                item.asset_path = "fixture://asset/" + hashlib.sha256(item.asset_bytes).hexdigest()
        snapshot, inserted = persist_structural(repository, parsed, source,
                                               pdf_path=path if fmt is SourceFormat.PDF else None)
        assert inserted == (iteration == 0)
        snapshots.append(snapshot)
    assert snapshots[0] == snapshots[1]
    first = snapshots[0]
    changed_spec = first.knowledge_revision.processing.model_copy(update={"mapper_version": "m2a-2"})
    changed, inserted = persist_structural(repository, parsed, source, spec=changed_spec,
                                          expected_latest_revision_id=first.knowledge_revision.id,
                                          pdf_path=path if fmt is SourceFormat.PDF else None)
    assert inserted and first.source_version == changed.source_version
    assert [n.id for n in first.structure] == [n.id for n in changed.structure]
    canonical, manifests = derived_chain(first)
    for manifest in manifests:
        repository.append_derived(manifest)
    graph = repository.get_lineage(first.knowledge_revision.id)
    assert manifests[-1].objects[0] in graph.trace(canonical, "downstream").objects
    assert canonical in graph.trace(manifests[-1].objects[0], "upstream").objects
    new_graph = repository.get_lineage(changed.knowledge_revision.id)
    assert all(obj.kind in {"source", "processing", "canonical"} for obj in new_graph.objects.values())
    assert manifests[-1].objects[0].key not in new_graph.objects
