"""Regression checks for live/demo isolation and truthful capability reporting."""

import pytest
from docgrain_api import fixtures, repository
from docgrain_api.main import app
from docgrain_api.routers import documents, versions
from docgrain_api.settings import Settings, get_settings
from fastapi.testclient import TestClient

client = TestClient(app)
PDF = {"workspace_id": "ws_test", "filename": "sample.pdf", "mime_type": "application/pdf", "byte_size": 4}


def test_live_is_the_default(monkeypatch):
    monkeypatch.delenv("USE_FIXTURES", raising=False)
    assert Settings().use_fixtures is False


def test_demo_is_explicit_and_labeled():
    response = client.get("/healthz")
    assert response.json()["mode"] == "demo"
    assert response.headers["X-Docgrain-Mode"] == "demo"
    chunks = client.get("/v1/versions/dver_2/chunks")
    assert chunks.json()
    assert chunks.headers["X-Docgrain-Mode"] == "demo"


def test_demo_uploads_never_touch_storage_queue_or_metadata(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("demo mode must not mutate metadata or contact storage/queue")

    for name in ("put_upload", "object_exists", "enqueue"):
        monkeypatch.setattr(documents, name, forbidden)
    monkeypatch.setattr(repository, "add", forbidden)
    assert client.post("/v1/documents", json=PDF).status_code == 409
    path = "/v1/documents/doc_7fk2/versions/dver_2"
    assert client.put(f"{path}/content", files={"file": ("sample.pdf", b"test", "application/pdf")}).status_code == 409
    assert client.post(f"{path}/uploaded").status_code == 409


def test_demo_artifacts_do_not_contact_storage(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("demo reads must not contact object storage")

    monkeypatch.setattr(documents, "get_text", forbidden)
    monkeypatch.setattr(versions, "storage_client", forbidden)
    assert client.get("/v1/documents/doc_7fk2/versions/dver_2/artifacts/document.md").status_code == 404
    assert client.get("/v1/versions/dver_2/pages/1/render").status_code == 404


def test_live_empty_repository_never_returns_demo_records(live_repository):
    assert client.get("/healthz").json()["mode"] == "live"
    for path in ("/v1/documents", "/v1/jobs"):
        response = client.get(path)
        assert response.json() == []
        assert response.headers["X-Docgrain-Mode"] == "live"
    for path in ("/v1/versions/dver_2", "/v1/versions/dver_2/pages", "/v1/versions/dver_2/tables",
                 "/v1/versions/dver_2/assets", "/v1/versions/dver_2/chunks"):
        assert client.get(path).status_code == 404


def test_live_fixture_shaped_ids_do_not_activate_demo(live_repository, monkeypatch):
    live_repository["versions"]["dver_2"] = fixtures.VERSIONS[0].model_copy(deep=True)
    monkeypatch.setattr(versions, "get_text", lambda _: '{"pages": [{"page_number": 1, "width": 100, "height": 200}]}')
    for artifact in ("chunks", "tables", "assets"):
        assert client.get(f"/v1/versions/dver_2/{artifact}").json() == []
    page = client.get("/v1/versions/dver_2/pages/1").json()
    assert page["confidence"] is None
    assert page["table_ids"] == []
    assert page["asset_ids"] == []
    assert page["width"] == 100
    assert client.get("/v1/versions/dver_2/chunks/boundaries").status_code == 501


def test_live_similarity_is_not_simulated(live_repository):
    assert client.get("/v1/chunks/chk_06").status_code == 501
    assert client.get("/v1/chunks/chk_06/neighbors").status_code == 501


def test_retry_never_reports_fake_acceptance(monkeypatch, live_repository):
    monkeypatch.setattr(documents, "enqueue", lambda _: pytest.fail("retry must not enqueue"))
    live_repository["versions"]["dver_2"] = fixtures.VERSIONS[0].model_copy(deep=True)
    for demo in (False, True):
        monkeypatch.setattr(get_settings(), "use_fixtures", demo)
        response = client.post("/v1/versions/dver_2/retry", json={"from_stage": "extract"})
        assert response.status_code == 501
        assert "no work was queued" in response.json()["detail"]


def test_live_diff_is_count_only_and_document_scoped(live_repository):
    head, base = (v.model_copy(deep=True) for v in fixtures.VERSIONS)
    live_repository["versions"].update({head.id: head, base.id: base})
    result = client.get(f"/v1/versions/{head.id}/diff?base={base.id}").json()
    assert result["entries"] == []
    assert result["chunk_delta"] == head.chunk_count - base.chunk_count
    base.document_id = "another_document"
    assert client.get(f"/v1/versions/{head.id}/diff?base={base.id}").status_code == 400


def test_demo_diff_respects_requested_direction():
    result = client.get("/v1/versions/dver_1/diff?base=dver_2").json()
    assert result["base_version_id"] == "dver_2"
    assert result["head_version_id"] == "dver_1"
    assert result["entries"] == []


@pytest.mark.parametrize("extension", ["docx", "txt", "xlsx", "pptx", "html"])
def test_unimplemented_formats_are_rejected_before_registration(extension, live_repository):
    response = client.post("/v1/documents", json={**PDF, "filename": f"sample.{extension}"})
    assert response.status_code == 415
    assert live_repository["documents"] == {}


def test_external_source_ingestion_is_explicitly_unavailable(live_repository):
    response = client.post("/v1/documents", json={**PDF, "source_uri": "s3://somewhere/source.pdf"})
    assert response.status_code == 501
    assert live_repository["documents"] == {}


def test_provider_inventory_does_not_claim_unmeasured_health(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-test-key")
    providers = {item["interface"]: item for item in client.get("/v1/providers/health").json()}
    for name in ("PageRenderer", "DocumentParser", "VisionProvider", "ObjectStorage"):
        assert providers[name]["healthy"] is None
    assert providers["VectorIndex"]["healthy"] is False
    assert providers["EmbeddingProvider"]["healthy"] is False
