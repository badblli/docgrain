"""Real save_review against isolated PostgreSQL and a unique versioned MinIO bucket.

No parser, provider or embedding runs. Sources/artifacts are pinned by real versioned puts;
fixtures come from tests.unit.test_manual_review (modern = processing-based, legacy = no processing).
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pytest
from docgrain_api import review_publication
from docgrain_api.canonical_repository import CanonicalConflict
from docgrain_api.main import app
from docgrain_api.output_repository import OutputRepository
from docgrain_api.review_publication import (
    StorageIntegrityError,
    save_review,
    verified_bytes,
)
from docgrain_api.routers import knowledge, reviews
from docgrain_api.settings import get_settings
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.ai_output import output_bundle
from docgrain_domain.canonical.review import build_review_revision
from docgrain_worker.output_writer import publish_outputs
from fastapi.testclient import TestClient
from minio.error import S3Error
from psycopg import sql

from tests.integration import test_ai_publication as output_fixtures
from tests.integration import test_m2a_repository as m2a_fixtures
from tests.unit.test_manual_review import (
    OCCURRED,
    legacy,
    modern,
    node_fields,
    prepared,
)
from tests.unit.test_n3_visuals import visual_snapshot

lifecycle_store = m2a_fixtures.lifecycle_store
output_bucket = output_fixtures.output_bucket


class Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass

    def release_conn(self):
        pass


class Faulty:
    """Real client except reads of keys containing `marker` are corrupted or missing."""

    def __init__(self, client, marker, mode):
        self._client, self._marker, self._mode = client, marker, mode

    def __getattr__(self, name):
        return getattr(self._client, name)

    def get_object(self, bucket, key, **kwargs):
        if self._marker not in key:
            return self._client.get_object(bucket, key, **kwargs)
        if self._mode == "missing":
            raise S3Error(None, "NoSuchVersion", "gone", key, "req", "host")
        real = self._client.get_object(bucket, key, **kwargs)
        try:
            data = real.read()
        finally:
            real.close()
            real.release_conn()
        return Body(data[:-1] + bytes([data[-1] ^ 1]))  # same size, different checksum


def ensure_document(connect, schema, snapshot):
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("INSERT INTO {} VALUES (%s, %s) ON CONFLICT DO NOTHING")
            .format(sql.Identifier(schema, "documents")),
            (snapshot.document_id, snapshot.workspace_id))


def pin(snapshot, client, bucket, source_bytes, artifacts=None):
    """Real versioned puts; rewrites only storage URIs/versions/size (ids come from the sha)."""
    data = snapshot.model_dump(mode="json")
    document_id = data["document_id"]
    source = data["source_version"]
    assert sha256(source_bytes).hexdigest() == source["content_sha256"]
    key = f"uploads/{document_id}/version-1/original"
    version = client.put_object(bucket, key, BytesIO(source_bytes), len(source_bytes),
                                content_type="application/octet-stream").version_id
    assert version and version != "null", "bucket must be versioned"
    source.update(storage_uri=f"s3://{bucket}/{key}?versionId={version}",
                  storage_version=version, byte_size=len(source_bytes))
    for artifact in data["artifacts"]:
        payload = artifacts[artifact["id"]]
        assert sha256(payload).hexdigest() == artifact["content_sha256"]
        key = f"artifacts/{document_id}/{artifact['id']}"
        version = client.put_object(bucket, key, BytesIO(payload), len(payload),
                                    content_type=artifact["mime_type"]).version_id
        artifact.update(storage_uri=f"s3://{bucket}/{key}?versionId={version}")
    return CanonicalKnowledgeSnapshot.model_validate(data)


def seed(store, bucket, kind="modern", *, publish=False):
    repo, connect, schema = store
    client, name = bucket
    if kind == "modern":
        base = pin(modern(), client, name, b"txt")
    else:
        _, source, image = visual_snapshot()
        base = pin(legacy(), client, name, source, {"artifact-image": image})
    ensure_document(connect, schema, base)
    assert repo.append(base, expected_latest_revision_id=None)
    if publish:
        publish_outputs(repo, base, client, name)
    return base


def change_set(base, text="Corrected text", **override):
    changes = [(node_fields(base, "review:text")[0], text)]
    if base.knowledge_revision.processing is not None:
        cell = node_fields(base, "review:table")[0]
        if cell.value != "Right":
            changes.append((cell, "Right"))
    else:
        cells = node_fields(base, "review:table")
        changes += [(cells[1], 6), (node_fields(base, kind="description")[0], "Site plan")]
    return prepared(base, *changes, **override)


def chunk_manifest(snapshot):
    manifest = output_bundle(snapshot)[1]
    return manifest.manifest() if manifest.chunks else None


def assert_invisible(repo, connect, schema, base, candidate, heads, history_len):
    outputs = OutputRepository(connect, schema)
    assert repo.get_heads(base.document_id) == heads
    assert repo.get_snapshot(candidate.knowledge_revision.id) is None
    assert outputs.get_outputs(candidate.knowledge_revision.id) is None
    manifest = chunk_manifest(candidate)
    assert manifest is None or repo.get_derivation(manifest.revision.id) is None
    assert len(repo.review_history(base.document_id)) == history_len


@pytest.mark.parametrize("kind", ["modern", "legacy"])
def test_save_publishes_revision_head_outputs_and_chunks_keeping_source_unchanged(
        lifecycle_store, output_bucket, kind):
    repo, connect, schema = lifecycle_store
    client, bucket = output_bucket
    base = seed(lifecycle_store, output_bucket, kind, publish=kind == "modern")
    if kind == "modern":
        repo.approve(base.document_id, base.workspace_id, base.knowledge_revision.id,
                     expected_approved_revision_id=None)
    approved = repo.get_heads(base.document_id)[1]
    outputs = OutputRepository(connect, schema)
    parent_outputs = outputs.get_outputs(base.knowledge_revision.id)
    parent_dump = repo.get_snapshot(base.knowledge_revision.id).model_dump(mode="json")
    request = change_set(base)

    candidate, inserted = save_review(repo, base, request, client, bucket)

    assert inserted
    revision = candidate.knowledge_revision
    assert revision.parent_revision_id == base.knowledge_revision.id
    assert repo.get_heads(base.document_id) == (revision.id, approved)  # approval never moves
    stored = repo.get_snapshot(revision.id)
    assert stored == candidate
    assert repo.get_snapshot(base.knowledge_revision.id).model_dump(mode="json") == parent_dump
    assert stored.source_version == base.source_version
    assert stored.evidence == base.evidence and stored.artifacts == base.artifacts
    assert stored.schema_version == base.schema_version
    assert (stored.knowledge_revision.processing is None) == (base.knowledge_revision.processing is None)
    assert stored.knowledge_revision.coverage == base.knowledge_revision.coverage

    publication = outputs.get_outputs(revision.id)
    assert publication is not None and publication.revision.processing_revision_id == revision.id
    expected_files = output_bundle(candidate)[3]
    assert {f.name for f in publication.files} == set(expected_files)
    for item in publication.files:
        stored_bytes = verified_bytes(client, bucket, item.storage_uri, item.content_sha256, item.byte_size)
        assert stored_bytes == expected_files[item.name]
        assert f"/{base.document_id}/{revision.id}/" in item.storage_uri
    assert b"Corrected text" in expected_files["ai.json"]
    if parent_outputs is not None:
        assert outputs.get_outputs(base.knowledge_revision.id) == parent_outputs
    manifest = chunk_manifest(candidate)
    assert manifest is not None and repo.get_derivation(manifest.revision.id) == manifest

    history = repo.review_history(base.document_id)
    assert history[0]["revision_id"] == revision.id and history[0]["kind"] == "manual_review"
    assert history[0]["reviewer_id"] == "reviewer"

    # exact replay: same row, no second insert, outputs/heads untouched
    replay, inserted = save_review(repo, base, request, client, bucket)
    assert not inserted and replay == candidate
    assert repo.get_heads(base.document_id) == (revision.id, approved)
    assert outputs.get_outputs(revision.id) == publication
    assert len(repo.review_history(base.document_id)) == len(history)

    # same operation id with another payload is a conflict and changes nothing
    other = change_set(base, text="A different correction")
    with pytest.raises(CanonicalConflict, match="operation ID"):
        save_review(repo, base, other, client, bucket)
    assert repo.get_heads(base.document_id) == (revision.id, approved)
    assert repo.get_snapshot(build_review_revision(base, other).knowledge_revision.id) is None


def test_two_consecutive_reviews_chain_and_old_state_stays_replayable(lifecycle_store, output_bucket):
    repo, connect, schema = lifecycle_store
    client, bucket = output_bucket
    base = seed(lifecycle_store, output_bucket, publish=True)
    first, _ = save_review(repo, base, change_set(base, "First"), client, bucket)
    first_dump = repo.get_snapshot(first.knowledge_revision.id).model_dump(mode="json")
    second_request = change_set(first, "Second", operation_id="operation-2",
                                occurred_at=OCCURRED + timedelta(hours=1))
    second, inserted = save_review(repo, first, second_request, client, bucket)
    assert inserted and second.knowledge_revision.parent_revision_id == first.knowledge_revision.id
    assert repo.get_heads(base.document_id) == (second.knowledge_revision.id, None)
    assert repo.get_snapshot(first.knowledge_revision.id).model_dump(mode="json") == first_dump
    assert second.source_version == base.source_version and second.evidence == base.evidence
    assert [h["revision_id"] for h in repo.review_history(base.document_id)[:2]] == [
        second.knowledge_revision.id, first.knowledge_revision.id]
    outputs = OutputRepository(connect, schema)
    assert all(outputs.get_outputs(s.knowledge_revision.id) for s in (base, first, second))
    assert b"Second" in output_bundle(second)[3]["ai.json"]

    # replaying the first review against its old base is still idempotent after the head moved
    replay, inserted = save_review(repo, base, change_set(base, "First"), client, bucket)
    assert not inserted and replay == first
    # a new operation on the stale base loses the head check and leaves no trace
    stale = change_set(base, "Late", operation_id="operation-late")
    with pytest.raises(CanonicalConflict, match="head changed"):
        save_review(repo, base, stale, client, bucket)
    candidate = build_review_revision(base, stale)
    assert_invisible(repo, connect, schema, base, candidate,
                     (second.knowledge_revision.id, None), history_len=3)


def test_publication_failure_after_append_rolls_back_head_candidate_and_chunks(
        lifecycle_store, output_bucket, monkeypatch):
    repo, connect, schema = lifecycle_store
    client, bucket = output_bucket
    base = seed(lifecycle_store, output_bucket, publish=True)
    request = change_set(base)
    candidate = build_review_revision(base, request)
    assert chunk_manifest(candidate) is not None

    def failing_publish(self, publication):
        raise RuntimeError("publication failed after append")

    with monkeypatch.context() as patch:
        patch.setattr(review_publication.OutputRepository, "publish_outputs", failing_publish)
        with pytest.raises(RuntimeError, match="after append"):
            save_review(repo, base, request, client, bucket)
    assert_invisible(repo, connect, schema, base, candidate, (base.knowledge_revision.id, None), 1)
    assert repo.find_review_operation(base.document_id, request.operation_id) is None

    retried, inserted = save_review(repo, base, request, client, bucket)  # objects are reusable
    assert inserted and retried == candidate
    assert repo.get_heads(base.document_id) == (candidate.knowledge_revision.id, None)
    assert OutputRepository(connect, schema).get_outputs(candidate.knowledge_revision.id) is not None


@pytest.mark.parametrize("kind,marker,mode,error", [
    ("modern", "/original", "corrupt", StorageIntegrityError),
    ("modern", "/original", "missing", S3Error),
    ("modern", "knowledge/", "corrupt", StorageIntegrityError),
    ("legacy", "artifacts/", "corrupt", StorageIntegrityError),
    ("legacy", "artifacts/", "missing", S3Error),
])
def test_source_artifact_or_output_integrity_failure_leaves_no_visible_head(
        lifecycle_store, output_bucket, kind, marker, mode, error):
    repo, connect, schema = lifecycle_store
    client, bucket = output_bucket
    base = seed(lifecycle_store, output_bucket, kind)
    request = change_set(base)
    candidate = build_review_revision(base, request)
    with pytest.raises(error):
        save_review(repo, base, request, Faulty(client, marker, mode), bucket)
    assert_invisible(repo, connect, schema, base, candidate, (base.knowledge_revision.id, None), 1)
    saved, inserted = save_review(repo, base, request, client, bucket)  # healthy storage retry
    assert inserted and saved == candidate


def test_unpinned_source_is_rejected_before_anything_is_written(lifecycle_store, output_bucket):
    repo, connect, schema = lifecycle_store
    client, bucket = output_bucket
    base = modern()  # fixture:// original
    ensure_document(connect, schema, base)
    repo.append(base, expected_latest_revision_id=None)
    request = change_set(base)
    with pytest.raises(StorageIntegrityError):
        save_review(repo, base, request, client, bucket)
    assert_invisible(repo, connect, schema, base, build_review_revision(base, request),
                     (base.knowledge_revision.id, None), 1)


def test_concurrent_distinct_reviews_have_one_cas_winner(lifecycle_store, output_bucket):
    repo, connect, schema = lifecycle_store
    client, bucket = output_bucket
    base = seed(lifecycle_store, output_bucket, publish=True)
    requests = [change_set(base, text, operation_id=f"operation-{text}") for text in ("Alpha", "Beta")]
    candidates = [build_review_revision(base, r) for r in requests]
    barrier = threading.Barrier(2, timeout=60)

    def attempt(request):
        barrier.wait()
        try:
            return save_review(repo, base, request, client, bucket)[1]
        except CanonicalConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, requests))
    assert sorted(map(str, results)) == ["True", "conflict"]
    winner = candidates[results.index(True)]
    loser = candidates[results.index("conflict")]
    assert repo.get_heads(base.document_id) == (winner.knowledge_revision.id, None)
    assert repo.get_snapshot(winner.knowledge_revision.id) == winner
    outputs = OutputRepository(connect, schema)
    assert outputs.get_outputs(winner.knowledge_revision.id) is not None
    assert repo.get_snapshot(loser.knowledge_revision.id) is None
    assert outputs.get_outputs(loser.knowledge_revision.id) is None
    assert [h["kind"] for h in repo.review_history(base.document_id)].count("manual_review") == 1


def test_api_workspace_preview_save_replay_and_pinned_source_end_to_end(
        lifecycle_store, output_bucket, monkeypatch):
    repo, _, _ = lifecycle_store
    client, bucket = output_bucket
    base = seed(lifecycle_store, output_bucket, publish=True)
    settings = get_settings()
    monkeypatch.setattr(settings, "use_fixtures", False)
    monkeypatch.setattr(settings, "canonical_persistence_enabled", True)
    monkeypatch.setattr(settings, "s3_bucket", bucket)
    monkeypatch.setattr(settings, "api_public_url", "http://api.test")
    document = SimpleNamespace(id=base.document_id, workspace_id=base.workspace_id)
    monkeypatch.setattr(knowledge, "_store", lambda: repo)
    monkeypatch.setattr(reviews, "storage_client", lambda: client)
    monkeypatch.setattr(reviews.metadata, "get_document", lambda i: document if i == document.id else None)
    monkeypatch.setattr(reviews.metadata, "get_version", lambda *_: None)
    api = TestClient(app)
    path = f"/v1/documents/{base.document_id}/review"

    workspace = api.get(path).json()
    assert workspace["latest_revision_id"] == base.knowledge_revision.id and workspace["can_edit"]
    field = next(f for f in workspace["fields"] if f["kind"] == "text" and f["editable"])
    body = {"base_revision_id": base.knowledge_revision.id,
            "base_snapshot_sha256": workspace["snapshot_sha256"], "operation_id": "api-operation",
            "occurred_at": OCCURRED.isoformat(), "reviewer_id": "reviewer", "reason": "Checked source",
            "changes": [{"field_id": field["field_id"], "before": field["value"], "after": "Via API"}]}
    preview = api.post(path + "s/preview", json=body)
    assert preview.status_code == 200 and repo.get_heads(base.document_id)[0] == base.knowledge_revision.id
    save = body | {"preview_id": preview.json()["proposal_id"], "confirmed_source": True}
    saved = api.post(path + "s", json=save)
    assert saved.status_code == 200, saved.text
    revision_id = saved.json()["revision_id"]
    assert saved.json() == {"revision_id": revision_id, "parent_revision_id": base.knowledge_revision.id,
                            "inserted": True, "latest_revision_id": revision_id,
                            "approved_revision_id": None, "output_published": True}
    replay = api.post(path + "s", json=save).json()
    assert replay["inserted"] is False and replay["revision_id"] == revision_id

    assert api.post(path + "s/preview", json=body).status_code == 409  # base is no longer the head
    latest = api.get(path).json()
    assert latest["latest_revision_id"] == revision_id
    assert latest["history"][0]["kind"] == "manual_review" and latest["history"][0]["reviewer_id"] == "reviewer"
    assert api.get(path, params={"revision_id": base.knowledge_revision.id}).json()["can_edit"] is False
    source = api.get(f"/v1/knowledge/revisions/{revision_id}/source")
    assert source.status_code == 200 and source.content == b"txt"




def test_history_uses_server_record_time_not_self_reported_review_clock(lifecycle_store, output_bucket):
    repo, _connect, _schema = lifecycle_store
    client, bucket = output_bucket
    base = seed(lifecycle_store, output_bucket)
    # Deliberately old client timestamps must not move a new review before its parent in the UI.
    first, _ = save_review(repo, base, change_set(base, "First", occurred_at=OCCURRED.replace(year=2000)), client, bucket)
    second, _ = save_review(repo, first, change_set(first, "Second", operation_id="clock-2",
                                                 occurred_at=OCCURRED.replace(year=1999)), client, bucket)
    history = repo.review_history(base.document_id)
    assert [h["revision_id"] for h in history] == [second.knowledge_revision.id, first.knowledge_revision.id, base.knowledge_revision.id]
    assert history[0]["created_at"] >= history[1]["created_at"] >= history[2]["created_at"]
    assert second.metadata["manual_review"]["occurred_at"].startswith("1999-")
