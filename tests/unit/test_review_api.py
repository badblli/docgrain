"""HTTP contract of the revision review workspace, preview, save and pinned source download.

Storage, metadata and the canonical store are replaced by in-memory doubles; the router,
the pure review domain and the real publication helpers (verified_source) run unmocked.
"""

from types import SimpleNamespace

import pytest
from docgrain_api.canonical_repository import CanonicalConflict
from docgrain_api.main import app
from docgrain_api.review_publication import StorageIntegrityError
from docgrain_api.routers import knowledge, reviews
from docgrain_api.settings import get_settings
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.lifecycle import digest
from docgrain_domain.canonical.review import (
    build_review_revision,
    preview_review,
    review_fields,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from minio.error import S3Error

from tests.unit.test_manual_review import legacy, modern, node_fields, prepared, request

client = TestClient(app)
SOURCE = b"txt"  # modern()/mapped_snapshot source content_sha256 is sha256("txt")
FILENAME = "İzmir rapor.txt"


class FakeStore:
    """Read-only canonical store; any write-ish call fails the test."""

    def __init__(self, *snapshots, heads):
        self.snapshots = {s.knowledge_revision.id: s for s in snapshots}
        self.heads = heads
        self.document_id = snapshots[0].document_id
        self.history = []

    def get_heads(self, document_id):
        return self.heads if document_id == self.document_id else None

    def get_snapshot(self, revision_id):
        return self.snapshots.get(revision_id)

    def review_history(self, document_id):
        return self.history

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"unexpected canonical store call: {name}")


class Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeMinio:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.calls = []

    def get_object(self, bucket, key, version_id=None):
        self.calls.append((bucket, key, version_id))
        if (bucket, key, version_id) not in self.objects:
            raise S3Error(None, "NoSuchVersion", "missing", key, "req", "host")
        return Body(self.objects[(bucket, key, version_id)])


def forbidden_save(*_args, **_kwargs):
    raise AssertionError("save_review must not run")


@pytest.fixture
def install(monkeypatch):
    """Wires the router to a FakeStore; returns (store, document namespace)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "use_fixtures", False)
    monkeypatch.setattr(settings, "canonical_persistence_enabled", True)
    monkeypatch.setattr(settings, "s3_bucket", "bucket")
    monkeypatch.setattr(settings, "api_public_url", "http://api.test")

    def wire(*snapshots, heads=None, workspace_id=None, version=None):
        first = snapshots[0]
        store = FakeStore(*snapshots, heads=heads or (first.knowledge_revision.id, None))
        document = SimpleNamespace(
            id=first.document_id, workspace_id=workspace_id or first.workspace_id,
            filename=first.source_version.filename,
        )
        monkeypatch.setattr(knowledge, "_store", lambda: store)
        monkeypatch.setattr(reviews.metadata, "get_document",
                            lambda document_id: document if document_id == document.id else None)
        monkeypatch.setattr(reviews.metadata, "get_version", lambda document_id, version_id: version)
        monkeypatch.setattr(reviews, "save_review", forbidden_save)
        return store, document

    return wire


def review_path(snapshot, suffix=""):
    return f"/v1/documents/{snapshot.document_id}/review{suffix}"


def edit(snapshot, after="Corrected text", **override):
    text = node_fields(snapshot, "review:text")[0]
    return request(snapshot, (text, after), **override)


def pinned(snapshot, *, filename=FILENAME, data=SOURCE, version="v-123", name="ver-1"):
    value = snapshot.model_dump(mode="json")
    value["source_version"].update(
        storage_uri=f"s3://bucket/uploads/{snapshot.document_id}/{name}/original?versionId={version}",
        storage_version=version, byte_size=len(data), filename=filename,
    )
    return CanonicalKnowledgeSnapshot.model_validate(value)


# --- workspace -------------------------------------------------------------------------


def test_workspace_returns_current_revision_fields_and_unpinned_source(install):
    base = modern()
    store, _ = install(base)
    store.history = [{"revision_id": base.knowledge_revision.id, "parent_revision_id": None,
                      "created_at": "2026-01-01T00:00:00+00:00", "kind": "extraction",
                      "reviewer_id": None, "reason": None}]
    response = client.get(review_path(base))
    assert response.status_code == 200
    value = response.json()
    revision_id = base.knowledge_revision.id
    assert value["document_id"] == base.document_id
    assert value["latest_revision_id"] == revision_id and value["approved_revision_id"] is None
    assert value["snapshot_sha256"] == digest(base.model_dump(mode="json"))
    assert value["snapshot"]["knowledge_revision"]["id"] == revision_id
    assert value["can_edit"] is True
    assert value["fields"] == [f.model_dump(mode="json") for f in review_fields(base)]
    assert value["source"]["download_url"] == f"http://api.test/v1/knowledge/revisions/{revision_id}/source"
    assert value["source"]["filename"] == base.source_version.filename
    # fixture:// source is not a pinned upload: no invented version or pages
    assert value["source"]["document_version_id"] is None and value["source"]["pages"] == []
    assert [h["kind"] for h in value["history"]] == ["extraction"]
    assert value["warnings"]


def test_workspace_pdf_pages_only_for_the_matching_persisted_version(install):
    base = legacy()  # generic PDF fixture
    assert base.source_version.mime_type == "application/pdf"
    sha = base.source_version.content_sha256
    value = base.model_dump(mode="json")
    value["source_version"].update(
        storage_uri=f"s3://bucket/uploads/{base.document_id}/ver-1/original?versionId=v1",
        storage_version="v1")
    snapshot = CanonicalKnowledgeSnapshot.model_validate(value)
    install(snapshot, version=SimpleNamespace(id="ver-1", content_sha256=sha, page_count=2))
    source = client.get(review_path(snapshot)).json()["source"]
    assert source["document_version_id"] == "ver-1"
    assert source["pages"] == [
        {"page_number": n, "render_url": f"http://api.test/v1/versions/ver-1/pages/{n}/render"}
        for n in (1, 2)]
    install(snapshot, version=SimpleNamespace(id="ver-1", content_sha256="0" * 64, page_count=2))
    source = client.get(review_path(snapshot)).json()["source"]
    assert source["document_version_id"] is None and source["pages"] == []


def test_historical_revision_is_readable_but_not_editable(install):
    base = modern()
    child = build_review_revision(base, prepared(base, (node_fields(base, "review:text")[0], "Child")))
    install(base, child, heads=(child.knowledge_revision.id, None))
    old = client.get(review_path(base), params={"revision_id": base.knowledge_revision.id}).json()
    assert old["latest_revision_id"] == child.knowledge_revision.id
    assert old["snapshot"]["knowledge_revision"]["id"] == base.knowledge_revision.id
    assert old["can_edit"] is False and len(old["warnings"]) == 3
    new = client.get(review_path(base)).json()
    assert new["snapshot"]["knowledge_revision"]["id"] == child.knowledge_revision.id
    assert new["can_edit"] is True


def test_foreign_missing_and_headless_revisions_are_404(install):
    base = modern()
    other = legacy()
    assert other.document_id != base.document_id, "needs a revision of another document"
    store, _ = install(base, other)
    foreign = other.knowledge_revision.id
    assert client.get(review_path(base), params={"revision_id": foreign}).status_code == 404
    assert client.get(review_path(base), params={"revision_id": "missing"}).status_code == 404
    assert client.get("/v1/documents/unknown/review").status_code == 404
    assert client.post(review_path(base, "s/preview"), json=edit(base).model_dump(mode="json")
                       | {"base_revision_id": foreign}).status_code == 404
    store.heads = (None, None)
    assert client.get(review_path(base)).status_code == 404
    store.heads = None
    assert client.get(review_path(base)).status_code == 404


def test_workspace_scope_is_protected_on_every_review_endpoint(install):
    base = modern()
    install(base, workspace_id="another-workspace")
    body = edit(base).model_dump(mode="json")
    assert client.get(review_path(base)).status_code == 404
    assert client.post(review_path(base, "s/preview"), json=body).status_code == 404
    save = prepared(base, (node_fields(base, "review:text")[0], "X")).model_dump(mode="json")
    assert client.post(review_path(base, "s"), json=save).status_code == 404


def test_demo_mode_never_fabricates_a_snapshot_and_rejects_saves(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "use_fixtures", True)
    monkeypatch.setattr(reviews, "save_review", forbidden_save)
    base = modern()
    document = SimpleNamespace(id=base.document_id, workspace_id=base.workspace_id)
    monkeypatch.setattr(reviews.metadata, "get_document", lambda _id: document)
    # the real knowledge store is deliberately left in place: demo has no canonical rows
    assert client.get(review_path(base)).status_code == 404
    body = edit(base).model_dump(mode="json")
    assert client.post(review_path(base, "s/preview"), json=body).status_code == 404
    save = prepared(base, (node_fields(base, "review:text")[0], "X")).model_dump(mode="json")
    assert client.post(review_path(base, "s"), json=save).status_code == 409


# --- preview ---------------------------------------------------------------------------


def test_preview_is_pure_deterministic_and_matches_the_domain(install):
    base = modern()
    store, _ = install(base)
    before = base.model_dump(mode="json")
    req = edit(base)
    first = client.post(review_path(base, "s/preview"), json=req.model_dump(mode="json"))
    second = client.post(review_path(base, "s/preview"), json=req.model_dump(mode="json"))
    assert first.status_code == 200 and first.json() == second.json()
    assert first.json() == preview_review(base, req).model_dump(mode="json")
    assert first.json()["review_status"] == "proposed" and len(first.json()["changes"]) == 1
    assert store.snapshots == {base.knowledge_revision.id: base}  # FakeStore forbids writes
    assert base.model_dump(mode="json") == before and store.heads == (base.knowledge_revision.id, None)


def test_preview_conflicts_are_409_and_invalid_edits_are_422(install):
    base = modern()
    child = build_review_revision(base, prepared(base, (node_fields(base, "review:text")[0], "Child")))
    store, _ = install(base, child)
    path = review_path(base, "s/preview")
    good = edit(base).model_dump(mode="json")
    assert client.post(path, json=good).status_code == 200
    store.heads = (child.knowledge_revision.id, None)  # head moved after the user loaded base
    assert client.post(path, json=good).status_code == 409
    store.heads = (base.knowledge_revision.id, None)

    assert client.post(path, json=good | {"base_snapshot_sha256": "0" * 64}).status_code == 409
    stale = good | {"changes": [{**good["changes"][0], "before": "Old text"}]}
    assert client.post(path, json=stale).status_code == 409

    noop = good | {"changes": [{**good["changes"][0], "after": good["changes"][0]["before"]}]}
    assert client.post(path, json=noop).status_code == 422
    bare = node_fields(base, "review:text-bare")[0]
    readonly = request(base, (bare, "x")).model_dump(mode="json")
    assert client.post(path, json=readonly).status_code == 422
    unknown = good | {"changes": [{"field_id": "missing", "before": "a", "after": "b"}]}
    assert client.post(path, json=unknown).status_code == 422
    duplicate = good | {"changes": good["changes"] * 2}
    assert client.post(path, json=duplicate).status_code == 422
    assert client.post(path, json=good | {"changes": []}).status_code == 422
    assert client.post(path, json=good | {"occurred_at": "2026-03-01T12:00:00"}).status_code == 422
    assert client.post(path, json=good | {"reviewer_id": " "}).status_code == 422
    assert client.post(path, json=good | {"changes": [{**good["changes"][0], "after": ["a"]}]}).status_code == 422


# --- save ------------------------------------------------------------------------------


def test_save_requires_explicit_boolean_confirmation_before_any_work(install):
    base = modern()
    install(base)
    path = review_path(base, "s")
    good = prepared(base, (node_fields(base, "review:text")[0], "Corrected")).model_dump(mode="json")
    assert good["confirmed_source"] is True
    for confirmation in (False, "true", 1, None):
        assert client.post(path, json=good | {"confirmed_source": confirmation}).status_code == 422
    missing = {k: v for k, v in good.items() if k != "confirmed_source"}
    assert client.post(path, json=missing).status_code == 422
    missing = {k: v for k, v in good.items() if k != "preview_id"}
    assert client.post(path, json=missing).status_code == 422  # forbidden_save never ran


def test_save_returns_new_head_unchanged_approval_and_idempotent_flag(install, monkeypatch):
    base = modern()
    store, _ = install(base)
    store.heads = (base.knowledge_revision.id, "approved-revision")
    sentinel = object()
    monkeypatch.setattr(reviews, "storage_client", lambda: sentinel)
    calls = []

    def fake_save(repository, snapshot, save, minio, bucket):
        calls.append((repository, snapshot, save, minio, bucket))
        child = build_review_revision(snapshot, save)
        inserted = child.knowledge_revision.id not in store.snapshots
        store.snapshots[child.knowledge_revision.id] = child
        store.heads = (child.knowledge_revision.id, store.heads[1])
        return child, inserted

    monkeypatch.setattr(reviews, "save_review", fake_save)
    path = review_path(base, "s")
    save = prepared(base, (node_fields(base, "review:text")[0], "Corrected")).model_dump(mode="json")
    response = client.post(path, json=save)
    assert response.status_code == 200
    value = response.json()
    child_id = store.heads[0]
    assert child_id != base.knowledge_revision.id
    assert value == {"revision_id": child_id, "parent_revision_id": base.knowledge_revision.id,
                     "inserted": True, "latest_revision_id": child_id,
                     "approved_revision_id": "approved-revision", "output_published": True}
    assert calls[0][1] == base and calls[0][3] is sentinel and calls[0][4] == "bucket"
    assert calls[0][2].confirmed_source is True and calls[0][2].operation_id == save["operation_id"]
    again = client.post(path, json=save).json()
    assert again["inserted"] is False and again["revision_id"] == child_id


@pytest.mark.parametrize("error,status", [
    (CanonicalConflict("latest head changed concurrently"), 409),
    (CanonicalConflict("operation ID already has another review payload"), 409),
    (ValueError("review before value is stale for this source revision"), 409),
    (ValueError("review base belongs to another source or processing revision"), 409),
    (ValueError("review field is read-only: formula"), 422),
    (ValueError("preview belongs to another source, revision or request"), 422),
    (StorageIntegrityError("source/asset/output checksum differs from pinned bytes"), 503),
    (S3Error("SlowDown", "busy", "res", "req", "host", None), 503),
    (OSError("connection reset"), 503),
])
def test_save_error_mapping_never_reports_a_commit(install, monkeypatch, error, status):
    base = modern()
    store, _ = install(base)
    monkeypatch.setattr(reviews, "storage_client", lambda: object())

    def failing(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(reviews, "save_review", failing)
    save = prepared(base, (node_fields(base, "review:text")[0], "Corrected")).model_dump(mode="json")
    response = client.post(review_path(base, "s"), json=save)
    assert response.status_code == status
    assert "revision_id" not in response.json()
    assert store.heads == (base.knowledge_revision.id, None)


# --- source download -------------------------------------------------------------------


def serve(install, monkeypatch, snapshot, objects):
    install(snapshot)
    minio = FakeMinio(objects)
    monkeypatch.setattr(reviews, "storage_client", lambda: minio)

    def get_revision(revision_id):
        if revision_id != snapshot.knowledge_revision.id:
            raise HTTPException(404, "revision not found")
        return snapshot

    monkeypatch.setattr(knowledge, "get_revision", get_revision)
    return minio


def test_source_download_is_version_pinned_with_correct_headers(install, monkeypatch):
    base = pinned(modern())
    key = f"uploads/{base.document_id}/ver-1/original"
    minio = serve(install, monkeypatch, base, {("bucket", key, "v-123"): SOURCE})
    response = client.get(f"/v1/knowledge/revisions/{base.knowledge_revision.id}/source")
    assert response.status_code == 200 and response.content == SOURCE
    assert minio.calls == [("bucket", key, "v-123")]  # never the unversioned latest object
    assert response.headers["content-type"].startswith(base.source_version.mime_type)
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''%C4%B0zmir%20rapor.txt"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in response.headers["cache-control"] and "private" in response.headers["cache-control"]
    workspace = client.get(review_path(base)).json()
    assert workspace["source"]["download_url"].endswith(
        f"/v1/knowledge/revisions/{base.knowledge_revision.id}/source")


def test_source_download_failures_are_explicit(install, monkeypatch):
    base = pinned(modern())
    key = f"uploads/{base.document_id}/ver-1/original"
    path = f"/v1/knowledge/revisions/{base.knowledge_revision.id}/source"

    serve(install, monkeypatch, base, {("bucket", key, "v-123"): b"tampered"})
    assert client.get(path).status_code == 503  # checksum/size differ from the pin

    serve(install, monkeypatch, base, {})
    assert client.get(path).status_code == 404  # version gone

    serve(install, monkeypatch, base, {("bucket", key, "v-123"): SOURCE})
    assert client.get("/v1/knowledge/revisions/missing/source").status_code == 404

    for update in (
        {"storage_uri": "fixture://original"},
        {"storage_uri": "s3://bucket/uploads/other-doc/ver-1/original?versionId=v-123"},
        {"storage_uri": f"s3://other-bucket/{key}?versionId=v-123"},
        {"storage_uri": f"s3://bucket/{key}?versionId=null", "storage_version": "null"},
        {"storage_uri": f"s3://bucket/{key}"},
        {"storage_version": "different"},
    ):
        value = base.model_dump(mode="json")
        value["source_version"].update(update)
        scoped = CanonicalKnowledgeSnapshot.model_validate(value)
        minio = serve(install, monkeypatch, scoped, {("bucket", key, "v-123"): SOURCE})
        assert client.get(path).status_code == 503, update
        assert minio.calls == [] or all(call[2] != "different" for call in minio.calls)
