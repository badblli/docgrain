"""U1 settings: explicit opt-in, isolation, secret hygiene and no model transport."""

import json
from uuid import uuid4

import httpx
import pytest
from docgrain_api import repository
from docgrain_api import workspace_settings as service
from docgrain_api import workspace_settings_repository as store
from docgrain_api.main import app
from docgrain_api.settings import get_settings
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

SENTINEL = "synthetic-secret-sentinel-for-u1-tests"


@pytest.fixture
def settings_store(live_repository, monkeypatch):
    catalog, models = {}, {}
    documents_workspaces = repository.list_workspaces
    calls = []

    def no_transport(*args, **kwargs):
        calls.append("model request")
        raise AssertionError("settings must never call a model transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_transport)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_transport)
    monkeypatch.setattr("docgrain_api.queue.enqueue", no_transport)

    def create(name):
        ws = f"ws_{uuid4().hex}"
        catalog[ws] = {"id": ws, "name": name, "documents": 0}
        return dict(catalog[ws])

    def listing():
        merged = {row["id"]: dict(row) for row in documents_workspaces()}
        for ws, row in catalog.items():
            merged[ws] = {**row, "documents": merged.get(ws, {}).get("documents", 0)}
        return list(merged.values())

    def save(ws, values):
        models[ws] = {**values, "settings_version": models.get(ws, {}).get("settings_version", 0) + 1}
        return dict(models[ws])

    monkeypatch.setattr(store, "create_workspace", create)
    monkeypatch.setattr(store, "read_model", lambda ws: dict(models[ws]) if ws in models else None)
    monkeypatch.setattr(store, "save_model", save)
    monkeypatch.setattr(repository, "list_workspaces", listing)
    monkeypatch.setattr(get_settings(), "docgrain_model_credential_profiles", json.dumps({
        "cloud": {"label": "Şirket bağlantısı", "api_key_env": "U1_TEST_KEY"},
        "local": {"label": "Yerel bağlantı", "api_key_env": None},
        "missing": {"label": "Hazırlanacak bağlantı", "api_key_env": "U1_MISSING_KEY"},
    }))
    monkeypatch.setenv("U1_TEST_KEY", SENTINEL)
    monkeypatch.delenv("U1_MISSING_KEY", raising=False)
    yield TestClient(app), catalog, models, calls
    assert calls == []


def create(client, name="Örnek Şirket"):
    response = client.post("/v1/workspaces", json={"name": name})
    assert response.status_code == 201
    assert response.json()["documents"] == 0
    return response.json()["id"]


def update(**overrides):
    return {"enabled": True, "base_url": "https://model.example/v1", "model": "example-model",
            "credential_id": "cloud", **overrides}


def test_empty_company_default_off_and_reopened_client(settings_store):
    client, catalog, models, _ = settings_store
    ws = create(client, "  Örnek Şirket  ")
    assert ws.startswith("ws_") and len(ws) == 35
    expected = {"id": ws, "name": "Örnek Şirket", "documents": 0}
    assert client.get("/v1/workspaces").json() == [expected]
    assert TestClient(app).get("/v1/workspaces").json() == [expected]
    assert catalog[ws] == expected
    assert client.get(f"/v1/workspaces/{ws}/model").json() == {
        "enabled": False, "base_url": "", "model": "", "credential_id": "",
        "credential_ready": False, "settings_version": 0,
    }
    assert models == {}
    with pytest.raises(service.ModelSettingsError) as error:
        service.resolve_workspace_model(ws)
    assert error.value.status_code == 409


def test_old_document_company_and_new_empty_company_coexist(settings_store, live_repository):
    from datetime import UTC, datetime

    from docgrain_domain import Document

    client, _, _, _ = settings_store
    now = datetime.now(UTC)
    live_repository["documents"]["doc_old"] = Document(
        id="doc_old", workspace_id="ws_old", title="Guide", filename="guide.txt",
        mime_type="text/plain", created_at=now, updated_at=now,
    )
    ws = create(client)
    rows = {row["id"]: row for row in client.get("/v1/workspaces").json()}
    assert rows["ws_old"] == {"id": "ws_old", "name": "ws_old", "documents": 1}
    assert rows[ws]["documents"] == 0
    assert client.get("/v1/workspaces/ws_old/model").json()["enabled"] is False
    assert client.put("/v1/workspaces/ws_old/model", json=update(credential_id="local")).status_code == 200


def test_company_isolation_versions_and_no_global_fallback(settings_store, monkeypatch):
    client, _, models, _ = settings_store
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    monkeypatch.setenv("DOCGRAIN_MODEL_API_KEY", SENTINEL)
    monkeypatch.setattr(get_settings(), "gemini_api_key", SENTINEL)
    a, b = create(client, "Şirket A"), create(client, "Şirket B")
    first = client.put(f"/v1/workspaces/{a}/model", json=update())
    assert first.status_code == 200 and first.json()["settings_version"] == 1
    assert first.json()["credential_ready"] is True
    assert client.get(f"/v1/workspaces/{b}/model").json()["enabled"] is False
    with pytest.raises(service.ModelSettingsError):
        service.resolve_workspace_model(b)
    assert b not in models
    assert client.put(f"/v1/workspaces/{b}/model", json=update(credential_id="")).status_code == 422
    assert client.put(f"/v1/workspaces/{a}/model", json=update(enabled=False)).json()["settings_version"] == 2
    with pytest.raises(service.ModelSettingsError):
        service.resolve_workspace_model(a, expected_version=1)


def test_allowlisted_profiles_local_model_and_key_rotation(settings_store, monkeypatch, caplog):
    client, _, models, _ = settings_store
    ws = create(client)
    profile_response = client.get(f"/v1/workspaces/{ws}/model/profiles")
    assert profile_response.json() == [
        {"id": "cloud", "label": "Şirket bağlantısı", "ready": True},
        {"id": "local", "label": "Yerel bağlantı", "ready": True},
        {"id": "missing", "label": "Hazırlanacak bağlantı", "ready": False},
    ]
    assert "U1_TEST_KEY" not in profile_response.text
    assert client.put(f"/v1/workspaces/{ws}/model", json=update()).status_code == 200
    resolved = service.resolve_workspace_model(ws, expected_version=1)
    assert resolved.enabled and resolved.api_key == SENTINEL
    assert resolved.base_url == "https://model.example/v1" and resolved.model == "example-model"
    assert SENTINEL not in repr(resolved)
    assert "api_key" not in resolved.model_dump()
    assert SENTINEL not in resolved.model_dump_json()
    assert SENTINEL not in json.dumps(jsonable_encoder(resolved))
    monkeypatch.setenv("U1_TEST_KEY", "synthetic-rotated-key")
    assert service.resolve_workspace_model(ws).api_key == "synthetic-rotated-key"
    assert service.resolve_workspace_model(ws).settings_version == 1
    monkeypatch.delenv("U1_TEST_KEY")
    assert client.get(f"/v1/workspaces/{ws}/model").json()["credential_ready"] is False
    with pytest.raises(service.ModelSettingsError) as error:
        service.resolve_workspace_model(ws)
    assert error.value.status_code == 409
    assert SENTINEL not in repr(error.value)
    assert client.put(f"/v1/workspaces/{ws}/model", json=update(credential_id="local", base_url="http://localhost:8000/v1")).status_code == 200
    assert service.resolve_workspace_model(ws, expected_version=2).api_key == ""
    assert SENTINEL not in json.dumps(models)
    assert SENTINEL not in client.get(f"/v1/workspaces/{ws}/model").text
    assert SENTINEL not in caplog.text


@pytest.mark.parametrize("fields", [
    {"api_key": SENTINEL}, {"api_key_env": "U1_TEST_KEY"}, {"credential_ready": True},
    {"settings_version": 100}, {"credential_id": "unknown"}, {"credential_id": "U1_TEST_KEY"},
    {"credential_id": "missing"}, {"base_url": ""}, {"model": ""}, {"enabled": "true"},
    {"enabled": None}, {"model": {"api_key": SENTINEL}},
    {"base_url": f"https://user:{SENTINEL}@model.example/v1"},
    {"base_url": f"https://model.example/v1?api_key={SENTINEL}"},
    {"base_url": f"https://model.example/v1#{SENTINEL}"},
    {"base_url": f"https://model.example/{SENTINEL}"}, {"model": SENTINEL},
    {"base_url": "ftp://model.example/v1"}, {"base_url": "https://model.example:invalid/v1"},
    {"base_url": "https://model.example:0/v1"}, {"base_url": "https://model.example/v1?"},
    {"base_url": "https://model.example\\@other.example/v1"},
    {"base_url": "https://model.example/v1\n"},
    {"base_url": "https://model.example/%73%65%63%72%65%74"},
    {"base_url": "https://model.example/token=synthetic-value"},
    {"base_url": "https://model.example/api_key/synthetic-value"},
    {"base_url": "https://user@model.example/v1"},
    {"base_url": "https://model.example/v1#"},
])
def test_invalid_input_is_redacted_and_not_persisted(settings_store, fields):
    client, _, models, _ = settings_store
    ws = create(client)
    response = client.put(f"/v1/workspaces/{ws}/model", json=update(**fields))
    assert response.status_code == 422
    assert SENTINEL not in response.text and "U1_TEST_KEY" not in response.text
    assert models == {}


def test_invalid_json_redacted_in_json_and_plain_accept(settings_store):
    client, _, _, _ = settings_store
    ws = create(client)
    for accept in ("application/json", "text/plain"):
        response = client.put(f"/v1/workspaces/{ws}/model", content='{"api_key":"' + SENTINEL,
                              headers={"Accept": accept, "Content-Type": "application/json"})
        assert response.status_code == 422 and SENTINEL not in response.text


def test_disabled_partial_settings_and_empty_profile_config(settings_store, monkeypatch):
    client, _, _, _ = settings_store
    ws = create(client)
    monkeypatch.setattr(get_settings(), "docgrain_model_credential_profiles", "{}")
    assert client.get(f"/v1/workspaces/{ws}/model/profiles").json() == []
    result = client.put(f"/v1/workspaces/{ws}/model", json={"enabled": False})
    assert result.status_code == 200 and result.json()["settings_version"] == 1
    assert result.json()["enabled"] is False
    assert client.put(f"/v1/workspaces/{ws}/model", json=update()).status_code == 422


@pytest.mark.parametrize("metadata", [
    "not json", "[]", '{"cloud":{"label":"Cloud","api_key":"' + SENTINEL + '"}}',
    '{"cloud":{"label":"Cloud","api_key_env":"INVALID=ENV"}}',
])
def test_invalid_server_profiles_fail_closed_without_echo(settings_store, monkeypatch, metadata):
    client, _, _, _ = settings_store
    ws = create(client)
    monkeypatch.setattr(get_settings(), "docgrain_model_credential_profiles", metadata)
    response = client.get(f"/v1/workspaces/{ws}/model/profiles")
    assert response.status_code == 503 and SENTINEL not in response.text
    with pytest.raises(service.ModelSettingsError) as error:
        service.resolve_workspace_model(ws)
    assert SENTINEL not in repr(error.value)


def test_removed_profile_and_wrong_version_fail_closed(settings_store, monkeypatch):
    client, _, _, _ = settings_store
    ws = create(client)
    client.put(f"/v1/workspaces/{ws}/model", json=update())
    with pytest.raises(service.ModelSettingsError) as error:
        service.resolve_workspace_model(ws, expected_version=0)
    assert error.value.status_code == 409
    monkeypatch.setattr(get_settings(), "docgrain_model_credential_profiles", "{}")
    assert client.get(f"/v1/workspaces/{ws}/model").json()["credential_ready"] is False
    with pytest.raises(service.ModelSettingsError):
        service.resolve_workspace_model(ws)


def test_failed_update_preserves_existing_settings(settings_store, monkeypatch):
    client, _, models, _ = settings_store
    ws = create(client)
    original = client.put(f"/v1/workspaces/{ws}/model", json=update()).json()
    response = client.put(f"/v1/workspaces/{ws}/model", json=update(api_key=SENTINEL))
    assert response.status_code == 422 and SENTINEL not in response.text
    assert client.get(f"/v1/workspaces/{ws}/model").json() == original
    monkeypatch.setenv("U1_TEST_KEY", "   ")
    assert client.put(f"/v1/workspaces/{ws}/model", json=update()).status_code == 422
    with pytest.raises(service.ModelSettingsError):
        service.resolve_workspace_model(ws)
    assert models[ws]["settings_version"] == 1


def test_demo_is_read_only_and_unknown_workspace(settings_store, monkeypatch):
    client, _, models, _ = settings_store
    ws = create(client)
    assert client.get("/v1/workspaces/ws_unknown/model").status_code == 404
    assert client.get("/v1/workspaces/ws_unknown/model/profiles").status_code == 404
    assert client.put("/v1/workspaces/ws_unknown/model", json=update()).status_code == 404
    monkeypatch.setattr(get_settings(), "use_fixtures", True)
    assert client.post("/v1/workspaces", json={"name": "Örnek"}).status_code == 409
    assert client.put(f"/v1/workspaces/{ws}/model", json=update()).status_code == 409
    assert models == {}


@pytest.mark.parametrize("body", [{"name": " "}, {"name": "A\nB"}, {"name": "x" * 201},
                                 {"name": "Örnek", "id": "ws_client"}, {"name": 123}])
def test_workspace_name_and_server_id_validation(settings_store, body):
    client, catalog, _, _ = settings_store
    assert client.post("/v1/workspaces", json=body).status_code == 422
    assert catalog == {}
