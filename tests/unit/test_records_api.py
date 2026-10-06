"""Pinned read-only API tests backed by actual immutable synthetic artifacts."""

import json
import socket

import pytest
from docgrain_api.records_repository import RecordsRepository
from docgrain_api.routers import records
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_records_export import fixture_revision

BASE = "/v1/workspaces/workspace-example/revisions/r1/collections"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("read path must not use network")
    store = RecordsRepository(tmp_path)
    store.publish(fixture_revision())
    store.publish(fixture_revision("r2", capacity=3))
    store.publish(fixture_revision("foreign-revision", workspace="workspace-foreign"))
    store.stage(fixture_revision("draft"))
    monkeypatch.setattr(records, "repository", lambda: store)
    app = FastAPI()
    app.include_router(records.router)
    app.include_router(records.workspace_router)
    with TestClient(app) as client:
        # Windows asyncio creates a loopback socketpair when its portal starts.
        # The application runs only after this point; every connect is blocked.
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        monkeypatch.setattr(socket, "create_connection", forbidden)
        yield client, store


def test_list_detail_empty_unknown_unpublished_and_foreign(setup):
    client, _ = setup
    response = client.get(BASE)
    assert response.status_code == 200
    assert response.json()["revision_id"] == "r1"
    assert "rooms" in response.json()["collections"]
    assert response.json()["mode"] == "preview"
    assert client.get(BASE + "/outlets").json() == []
    assert client.get(BASE + "/unknown").status_code == 404
    assert client.get(BASE.replace("r1", "unknown")).status_code == 404
    assert client.get(BASE.replace("r1", "draft")).status_code == 409
    assert client.get(BASE.replace("workspace-example", "foreign")).status_code == 404
    assert client.get(BASE.replace("r1", "foreign-revision")).status_code == 404
    assert client.get(BASE + "/rooms/records/foreign").status_code == 404
    assert client.post(BASE + "/rooms").status_code == 405
    assert client.put(BASE + "/rooms").status_code == 405
    assert client.delete(BASE + "/rooms").status_code == 405


def test_translation_record_and_context(setup):
    client, _ = setup
    row = next(r for r in client.get(BASE + "/rooms?lang=tr").json()
               if r["id"] == "rec-room")
    assert row["name"] == "Bahçe odası"
    response = client.get(BASE + "/rooms/records/rec-room?lang=tr")
    assert response.json() == row
    context = client.get(BASE + "/rooms/context?lang=tr")
    assert context.status_code == 200
    assert "Bahçe odası" in context.text and "Kaynaklar çelişiyor:" in context.text
    assert context.headers["x-docgrain-revision"] == "r1"
    assert next(r for r in client.get(BASE + "/rooms?lang=de").json()
                if r["id"] == "rec-room")["name"] == "Garden room"
    assert "Garden room" in client.get(BASE + "/rooms/context?lang=de").text


def test_mode_isolation_and_default_preview(setup):
    client, store = setup
    preview = client.get(BASE + "/rooms")
    approved = client.get(BASE + "/rooms?mode=approved")
    assert len(preview.json()) == 2 and len(approved.json()) == 1
    assert preview.headers["x-docgrain-publication-mode"] == "preview"
    assert approved.headers["x-docgrain-publication-mode"] == "approved"
    assert preview.headers["etag"] != approved.headers["etag"]
    assert client.get(BASE + "/rooms?mode=approved", headers={
        "If-None-Match": preview.headers["etag"]}).status_code == 200
    assert client.get(BASE + "/rooms?mode=approved", headers={
        "If-None-Match": approved.headers["etag"]}).status_code == 304
    assert "view" in preview.json()[0] or "view" in preview.json()[1]
    assert all("view" not in row for row in approved.json())
    assert "Kaynaklar çelişiyor:" in client.get(BASE + "/rooms/context").text
    assert "Kaynaklar çelişiyor:" not in client.get(
        BASE + "/rooms/context?mode=approved").text
    assert client.get(BASE + "/rooms/records/rec-proposed?mode=approved").status_code == 404
    assert client.get(BASE + "/rooms?mode=invalid").status_code == 422
    publication = store._path("workspace-example", "r1") / "published"
    assert (publication / "preview" / "rooms.json").is_file()
    assert (publication / "approved" / "rooms.json").is_file()


@pytest.mark.parametrize("suffix", ["", "/rooms", "/rooms/context", "/rooms/records/rec-room"])
def test_etag_304_revision_change_and_old_reads(setup, suffix):
    client, _ = setup
    first = client.get(BASE + suffix)
    etag = first.headers["etag"]
    for match in (etag, "W/" + etag, '"other", ' + etag, "*"):
        response = client.get(BASE + suffix, headers={"If-None-Match": match})
        assert response.status_code == 304 and response.content == b""
        assert response.headers["etag"] == etag
    assert client.get(BASE + suffix, headers={"If-None-Match": '"wrong"'}).status_code == 200
    assert client.get(BASE.replace("r1", "r2") + suffix).headers["etag"] != etag
    assert client.get(BASE + suffix).content == first.content


def test_no_regeneration_immutable_publish_and_checksum(setup, monkeypatch):
    client, store = setup
    old = client.get(BASE + "/rooms").content
    def forbidden(*args):
        pytest.fail("old publications must not regenerate")
    monkeypatch.setattr("docgrain_api.records_repository.export_bundle", forbidden)
    store.publish(fixture_revision())
    assert client.get(BASE + "/rooms").content == old
    assert client.get(BASE + "/rooms/context").status_code == 200
    with pytest.raises(ValueError, match="different content"):
        store.publish(fixture_revision(capacity=9))
    artifact = store._path("workspace-example", "r1") / "published" / "preview" / "rooms.json"
    artifact.write_bytes(b"[]")
    assert client.get(BASE + "/rooms").status_code == 503


def test_manifest_identity_gate_and_no_path_traversal(setup):
    client, store = setup
    assert next(r for r in client.get(BASE + "/rooms?lang=../../source").json()
                if r["id"] == "rec-room")["name"] == "Garden room"
    manifest = store._path("workspace-example", "r1") / "published" / "manifest.json"
    data = json.loads(manifest.read_bytes())
    data["workspace_id"] = "foreign"
    manifest.write_text(json.dumps(data))
    assert client.get(BASE).status_code == 404
    assert client.get(BASE + "/rooms?lang=../../source").status_code == 404


def test_list_revisions_newest_first(setup):
    client, _ = setup
    response = client.get("/v1/workspaces/workspace-example/revisions")
    assert response.status_code == 200
    assert response.json() == ["r2", "r1"]
    
    response = client.get("/v1/workspaces/workspace-foreign/revisions")
    assert response.status_code == 200
    assert response.json() == ["foreign-revision"]
    
    response = client.get("/v1/workspaces/unknown/revisions")
    assert response.status_code == 200
    assert response.json() == []
