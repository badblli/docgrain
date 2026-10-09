"""WP108: re-uploading a file whose last job failed must process it again, not reuse the failure."""

from types import SimpleNamespace

import pytest
from docgrain_api import repository
from docgrain_api.routers import documents
from docgrain_api.settings import get_settings

SHA = "b" * 64


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(documents.format_capabilities, "ensure_format_enabled", lambda fmt: fmt)
    monkeypatch.setattr(documents, "object_exists", lambda name: True)
    state = {"job": SimpleNamespace(id="job_1", status="failed"), "requeued": []}
    version = SimpleNamespace(id="ver_1", document_id="doc_1", workspace_id="ws_a", content_sha256=SHA,
                              source_uri="s3://bucket/uploads/ws_a/doc_1/ver_1/original")
    monkeypatch.setattr(repository, "list_versions", lambda *a: [version])
    monkeypatch.setattr(repository, "get_document", lambda d: SimpleNamespace(id="doc_1"))
    monkeypatch.setattr(repository, "job_for_version", lambda v: state["job"])

    def requeue(job_id, version_id):
        state["requeued"].append((job_id, version_id))
        state["job"] = SimpleNamespace(id=job_id, status="queued")

    monkeypatch.setattr(repository, "requeue_failed_job", requeue)
    captured = {}

    def response(**kwargs):
        captured.update(kwargs)
        return {"job_id": kwargs["job_id"], "deduplicated": kwargs["deduplicated"]}

    monkeypatch.setattr(documents, "RegisterResponse", response)
    return state, captured


def register():
    payload = documents.RegisterRequest(workspace_id="ws_a", filename="map.jpeg", mime_type="image/jpeg",
                                        byte_size=10, content_sha256=SHA)
    return documents._register_document(payload)


def test_failed_job_is_requeued_not_reused(client):
    state, captured = client
    register()
    assert state["requeued"] == [("job_1", "ver_1")]
    assert captured["job_id"] == "job_1" and captured["deduplicated"] is True


@pytest.mark.parametrize("status", ["done", "partial", "queued", "running"])
def test_other_jobs_are_reused_unchanged(client, status):
    state, captured = client
    state["job"] = SimpleNamespace(id="job_1", status=status)
    register()
    assert state["requeued"] == []
    assert captured["job_id"] == "job_1"
