"""Canonical HTTP reads expose validated stored snapshots without fixture fallbacks."""

import json
from pathlib import Path
from types import SimpleNamespace

from docgrain_api.main import app
from docgrain_api.routers import knowledge
from docgrain_domain.canonical import ArtifactRef, CanonicalKnowledgeSnapshot
from fastapi.testclient import TestClient

client = TestClient(app)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "canonical" / "generic-pdf.json"


class Store:
    def __init__(self, snapshot: CanonicalKnowledgeSnapshot) -> None:
        self.snapshot = snapshot
        self.heads: tuple[str | None, str | None] | None = (snapshot.knowledge_revision.id, None)

    def get_heads(self, document_id: str):
        return self.heads

    def get_snapshot(self, revision_id: str):
        return self.snapshot if revision_id == self.snapshot.knowledge_revision.id else None


def setup_live(monkeypatch):
    from docgrain_api.settings import get_settings

    snapshot = CanonicalKnowledgeSnapshot.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    store = Store(snapshot)
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(get_settings(), "canonical_persistence_enabled", True)
    monkeypatch.setattr(knowledge, "_store", lambda: store)
    monkeypatch.setattr(knowledge.repository, "get_document", lambda document_id: (
        SimpleNamespace(id=snapshot.document_id, workspace_id=snapshot.workspace_id)
        if document_id == snapshot.document_id else None
    ))
    return snapshot, store


def test_latest_snapshot_read(monkeypatch) -> None:
    snapshot, _ = setup_live(monkeypatch)
    response = client.get(f"/v1/documents/{snapshot.document_id}/knowledge")
    assert response.status_code == 200
    data = response.json()
    assert data["latest_revision_id"] == snapshot.knowledge_revision.id
    assert data["approved_revision_id"] is None
    assert data["snapshot"]["root_node_id"] == snapshot.root_node_id
    assert data["snapshot"]["schema_version"] == snapshot.schema_version


def test_specific_immutable_revision_read(monkeypatch) -> None:
    snapshot, _ = setup_live(monkeypatch)
    response = client.get(f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}")
    assert response.status_code == 200
    assert response.json()["knowledge_revision"]["id"] == snapshot.knowledge_revision.id


def test_revision_asset_is_served_only_from_referenced_versioned_object(monkeypatch) -> None:
    snapshot, store = setup_live(monkeypatch)
    artifact = ArtifactRef(id="artifact-image", role="source-image",
                           storage_uri=f"s3://docgrain/artifacts/{snapshot.document_id}/dver-1/structural/assets/hash?versionId=obj-1",
                           content_sha256="a" * 64, byte_size=4, mime_type="image/png")
    store.snapshot = snapshot.model_copy(update={
        "source_version": snapshot.source_version.model_copy(update={
            "storage_uri": f"s3://docgrain/uploads/{snapshot.document_id}/dver-1/original",
        }),
        "artifacts": [artifact],
    })
    seen = {}

    class Stored:
        def read(self):
            return b"PNG!"

        def close(self):
            pass

        def release_conn(self):
            pass

    class Storage:
        def get_object(self, bucket, name, *, version_id):
            seen.update(bucket=bucket, name=name, version_id=version_id)
            return Stored()

    monkeypatch.setattr(knowledge, "storage_client", lambda: Storage())
    response = client.get(f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}/artifacts/{artifact.id}")
    assert response.status_code == 200
    assert response.content == b"PNG!"
    assert response.headers["content-type"] == "image/png"
    assert seen == {"bucket": "docgrain", "name": f"artifacts/{snapshot.document_id}/dver-1/structural/assets/hash",
                    "version_id": "obj-1"}
    assert client.get(f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}/artifacts/not-referenced").status_code == 404


def test_missing_document_and_revision(monkeypatch) -> None:
    snapshot, store = setup_live(monkeypatch)
    assert client.get("/v1/documents/missing/knowledge").status_code == 404
    store.heads = None
    assert client.get(f"/v1/documents/{snapshot.document_id}/knowledge").status_code == 404
    assert client.get("/v1/knowledge/revisions/missing").status_code == 404


def test_document_and_revision_scope(monkeypatch) -> None:
    snapshot, store = setup_live(monkeypatch)
    store.snapshot = snapshot.model_copy(update={"document_id": "other-document"})
    assert client.get(f"/v1/documents/{snapshot.document_id}/knowledge").status_code == 404
    store.snapshot = snapshot
    monkeypatch.setattr(knowledge.repository, "get_document", lambda _: SimpleNamespace(
        id=snapshot.document_id, workspace_id="other-workspace"
    ))
    assert client.get(f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}").status_code == 404
    monkeypatch.setattr(knowledge.repository, "get_document", lambda _: SimpleNamespace(
        id=snapshot.document_id, workspace_id=snapshot.workspace_id
    ))
    monkeypatch.setattr(store, "get_snapshot", lambda _: snapshot)
    assert client.get("/v1/knowledge/revisions/other-revision").status_code == 404


def test_demo_never_produces_canonical_fixture(monkeypatch) -> None:
    from docgrain_api.settings import get_settings

    snapshot = CanonicalKnowledgeSnapshot.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    monkeypatch.setattr(get_settings(), "use_fixtures", True)
    monkeypatch.setattr(knowledge.repository, "get_document", lambda _: SimpleNamespace(
        id=snapshot.document_id, workspace_id=snapshot.workspace_id
    ))
    assert client.get(f"/v1/documents/{snapshot.document_id}/knowledge").status_code == 404
    assert client.get(f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}").status_code == 404
