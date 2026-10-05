"""Real PostgreSQL and opt-in versioned MinIO; no user bucket or source mutation."""

import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from docgrain_api.canonical_repository import CanonicalConflict
from docgrain_api.index_repository import IndexRepository
from docgrain_api.retrieval_cache import RevisionCache
from docgrain_api.retrieval_repository import RetrievalRepository
from docgrain_api.source_repository import SourceRepository
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import source_revision_id
from docgrain_domain.canonical.retrieval import RetrievalQuery, retrieve
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.canonical_writer import persist_structural
from docgrain_worker.index_lifecycle import refresh_index
from docgrain_worker.source_adapters import (
    FilesystemSource,
    IncompleteObservation,
    ObjectStoreSource,
)
from docgrain_worker.source_sync import sync_source
from docgrain_worker.structural import DocumentParser, VerifiedSource
from psycopg import sql

from tests.fixtures.incremental import FixtureEmbedder, index_spec
from tests.integration import test_m2a_repository as m2a_fixtures
from tests.unit.test_live_sources import observation

lifecycle_store = m2a_fixtures.lifecycle_store


def ledger(lifecycle_store):
    _, connect, schema = lifecycle_store
    repo = SourceRepository(connect, schema)
    repo.initialize()
    return repo


def test_cursor_cas_restart_coalescing_failure_and_duplicate_delivery(lifecycle_store):
    repo = ledger(lifecycle_store)
    first = {"a.txt": observation()}
    event = repo.reconcile("workspace-test", "connector", first, expected_generation=0)[0]
    assert repo.reconcile("workspace-test", "connector", first, expected_generation=0) == []
    with pytest.raises(CanonicalConflict):
        repo.reconcile("workspace-test", "connector", {}, expected_generation=0)
    seen = []
    def fail(change):
        seen.append(change.id)  # emulate publication then crash before acknowledgement
        raise RuntimeError("after publish")
    with pytest.raises(RuntimeError):
        repo.dispatch("workspace-test", "connector", fail)
    restarted = ledger(lifecycle_store)
    assert restarted.dispatch("workspace-test", "connector", lambda e: seen.append(e.id)) == 1
    assert seen == [event.id, event.id]
    assert restarted.dispatch("workspace-test", "connector", lambda e: seen.append(e.id)) == 0
    repo.reconcile("workspace-test", "connector", {}, expected_generation=1)
    newer = repo.reconcile("workspace-test", "connector", first, expected_generation=2)[0]
    received = []
    assert repo.dispatch("workspace-test", "connector", received.append) == 1
    assert received == [newer]  # delayed delete cannot win over newer upsert
    def attempt(content):
        try:
            return bool(repo.reconcile("workspace-test", "connector", {"a.txt": observation(content)},
                                       expected_generation=3))
        except CanonicalConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [b"two", b"three"])) == [False, True]
    assert repo.state("other-workspace", "connector") == (0, {})
    class BrokenScan:
        def scan(self):
            raise IncompleteObservation("partial inventory")
    before = repo.state("workspace-test", "connector")
    with pytest.raises(IncompleteObservation):
        sync_source(repo, "workspace-test", "connector", BrokenScan(), received.append)
    assert repo.state("workspace-test", "connector") == before
    # Direct SQL cannot replace immutable outbox/receipt history.
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException), repo._connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("DELETE FROM {}").format(repo._table("source_changes")))


def test_filesystem_change_to_canonical_index_delete_and_restore(lifecycle_store, tmp_path):
    repo = ledger(lifecycle_store)
    _, connect, schema = lifecycle_store
    canonical = IndexRepository(connect, schema)
    source = FilesystemSource(tmp_path)
    path = tmp_path / "a.txt"
    path.write_bytes(b"First searchable text")
    events = repo.reconcile("workspace-test", "files", source.scan(), expected_generation=0)
    document = events[0].document_id
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("INSERT INTO {} VALUES (%s,%s)").format(sql.Identifier(schema, "documents")),
                       (document, "workspace-test"))
    def publish(event):
        if event.action == "delete":
            return  # ledger publishes visibility tombstone, preserving immutable history
        obs = event.observation
        data = source.read(obs)
        verified_path = tmp_path / "verified.bin"  # excluded from source scan
        verified_path.write_bytes(data)
        verified = VerifiedSource(verified_path, obs.content_sha256, obs.byte_size)
        parsed = DocumentParser().parse(verified, SourceFormat.TXT)
        receipt = SourceVersion(id=source_revision_id("workspace-test", document, obs.content_sha256),
            document_id=document, workspace_id="workspace-test", content_sha256=obs.content_sha256,
            storage_uri=obs.uri, storage_version=obs.version, byte_size=obs.byte_size,
            mime_type="text/plain", filename=Path(obs.source_key).name,
            recorded_at=datetime(2026,1,1,tzinfo=UTC))
        heads = canonical.get_heads(document)
        head = heads[0] if heads else None
        snapshot, _ = persist_structural(canonical, parsed, receipt, expected_latest_revision_id=head)
        active = canonical.get_active("workspace-test", document)
        if active and active.revision.processing_revision_id == snapshot.knowledge_revision.id:
            return
        refresh_index(canonical, snapshot.knowledge_revision.id, index_spec(), FixtureEmbedder(),
                      expected_generation_id=active.revision.id if active else None)
    repo.dispatch("workspace-test", "files", publish)
    cache = RevisionCache()
    retrieval = RetrievalRepository(connect, schema, cache)
    query = RetrievalQuery(workspace_id="workspace-test", document_ids=[document], mode="lexical", text="First")
    old = canonical.get_heads(document)[0]
    assert retrieve(retrieval.read_views(query), query).hits
    path.write_bytes(b"Second replacement text")
    repo.reconcile("workspace-test", "files", source.scan(), expected_generation=1)
    repo.dispatch("workspace-test", "files", publish)
    new = canonical.get_heads(document)[0]
    assert new != old and canonical.get_snapshot(old) is not None
    assert not retrieve(retrieval.read_views(query), query).hits
    path.unlink()
    repo.reconcile("workspace-test", "files", source.scan(), expected_generation=2)
    repo.dispatch("workspace-test", "files", publish)
    for mode in ("structured", "direct", "lexical", "vector", "hybrid"):
        with pytest.raises(LookupError, match="deleted"):
            retrieval.read_views(query.model_copy(update={"mode": mode}))
        with pytest.raises(LookupError, match="deleted"):
            RetrievalRepository(connect, schema).read_views(query.model_copy(update={"mode": mode}))
    assert canonical.get_snapshot(new) is not None
    path.write_bytes(b"Second replacement text")
    repo.reconcile("workspace-test", "files", source.scan(), expected_generation=3)
    repo.dispatch("workspace-test", "files", publish)
    assert canonical.get_heads(document)[0] == new  # restore same bytes reuses canonical/index
    assert retrieval.read_views(query)


def test_versioned_object_store_update_delete_and_incomplete_scan(lifecycle_store):
    if not os.environ.get("DOCGRAIN_M2G_TEST_S3"):
        pytest.skip("set DOCGRAIN_M2G_TEST_S3 for isolated MinIO bucket test")
    from docgrain_api.storage import storage_client
    from minio.versioningconfig import ENABLED, VersioningConfig

    client = storage_client()
    bucket = "m2g-test-" + uuid.uuid4().hex
    client.make_bucket(bucket)
    client.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
    repo = ledger(lifecycle_store)
    adapter = ObjectStoreSource(client, bucket, "source/")
    try:
        client.put_object(bucket, "source/a.txt", io.BytesIO(b"first"), 5)
        first = adapter.scan()
        repo.reconcile("workspace-test", "objects", first, expected_generation=0)
        client.put_object(bucket, "source/a.txt", io.BytesIO(b"second"), 6)
        second = adapter.scan()
        assert first["source/a.txt"].version != second["source/a.txt"].version
        assert adapter.read(first["source/a.txt"]) == b"first"
        assert adapter.read(second["source/a.txt"]) == b"second"
        repo.reconcile("workspace-test", "objects", second, expected_generation=1)
        client.remove_object(bucket, "source/a.txt")
        assert adapter.scan() == {}
        assert repo.reconcile("workspace-test", "objects", {}, expected_generation=2)[0].action == "delete"
        broken = ObjectStoreSource(client, "nonexistent-" + uuid.uuid4().hex)
        with pytest.raises(IncompleteObservation):
            broken.scan()
        assert repo.state("workspace-test", "objects") == (3, {})
    finally:
        for obj in client.list_objects(bucket, recursive=True, include_version=True):
            client.remove_object(bucket, obj.object_name, version_id=obj.version_id)
        client.remove_bucket(bucket)
