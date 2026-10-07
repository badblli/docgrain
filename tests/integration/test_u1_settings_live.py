"""Real PostgreSQL reconnect/API restart persistence; synthetic companies only."""

import json
import os
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from docgrain_api import repository
from docgrain_api.main import app
from docgrain_api.settings import get_settings
from docgrain_api.workspace_settings import resolve_workspace_model
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row


@pytest.fixture
def postgres_settings(monkeypatch):
    database_url = os.environ.get("DOCGRAIN_M1_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires worker PostgreSQL: DOCGRAIN_M1_TEST_DATABASE_URL")
    schema = "u1_settings_test_" + uuid4().hex
    with psycopg.connect(database_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    @contextmanager
    def connect():
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            yield connection

    monkeypatch.setattr(repository, "_connection", connect)
    settings = get_settings()
    monkeypatch.setattr(settings, "use_fixtures", False)
    monkeypatch.setattr(settings, "canonical_persistence_enabled", False)
    monkeypatch.setattr(settings, "docgrain_model_credential_profiles", json.dumps({
        "local": {"label": "Yerel bağlantı", "api_key_env": None},
    }))
    try:
        yield connect
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_catalog_model_persist_across_connections_and_api_restart(postgres_settings):
    with TestClient(app) as client:
        response = client.post("/v1/workspaces", json={"name": "Örnek Şirket"})
        assert response.status_code == 201
        workspace = response.json()
        ws = workspace["id"]
        assert workspace == {"id": ws, "name": "Örnek Şirket", "documents": 0}
        assert client.get(f"/v1/workspaces/{ws}/model").json()["enabled"] is False
        other = client.post("/v1/workspaces", json={"name": "İkinci Şirket"}).json()["id"]
        update = {"enabled": True, "base_url": "http://local-model:8000/v1",
                  "model": "example-local", "credential_id": "local"}
        saved = client.put(f"/v1/workspaces/{ws}/model", json=update)
        assert saved.status_code == 200 and saved.json()["settings_version"] == 1

    # Fresh connections and a second API lifespan rerun the additive initialization.
    with TestClient(app) as reopened:
        rows = {row["id"]: row for row in reopened.get("/v1/workspaces").json()}
        assert rows[ws] == workspace
        assert rows[other]["documents"] == 0
        assert reopened.get(f"/v1/workspaces/{ws}/model").json() == saved.json()
        assert reopened.get(f"/v1/workspaces/{other}/model").json()["enabled"] is False
        assert resolve_workspace_model(ws, expected_version=1).api_key == ""
        assert reopened.put(f"/v1/workspaces/{ws}/model", json=update).json()["settings_version"] == 2
        with postgres_settings() as connection:
            connection.execute("""INSERT INTO documents
                (id, workspace_id, title, filename, mime_type, version_count, created_at, updated_at)
                VALUES ('doc_old', 'ws_old', 'Guide', 'guide.txt', 'text/plain', 1, now(), now()),
                       ('doc_new', %s, 'Notes', 'notes.txt', 'text/plain', 1, now(), now())""", (ws,))
        rows = {row["id"]: row for row in reopened.get("/v1/workspaces").json()}
        assert rows[ws] == {**workspace, "documents": 1}
        assert rows["ws_old"] == {"id": "ws_old", "name": "ws_old", "documents": 1}
        with postgres_settings() as connection:
            persisted = connection.execute("SELECT * FROM workspace_model_settings").fetchall()
        assert len(persisted) == 1
        assert persisted[0] == {"workspace_id": ws, **update, "settings_version": 2}
