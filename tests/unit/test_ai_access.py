"""Synthetic workspace schema, source fidelity, publication isolation and ranking."""

import socket
from copy import deepcopy

import pytest
from docgrain_api.ai_access import AIAccess
from docgrain_api.main import app as main_app
from docgrain_api.records_repository import RecordsRepository
from docgrain_api.routers import ai
from docgrain_records.merge_models import MergedRecord
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from test_records_export import candidate, fixture_revision
from test_schema_driven_records import accepted


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = RecordsRepository(tmp_path / "publications")
    revision = fixture_revision()
    revision.documents[0].document_name = "rooms.txt"
    store.publish(revision)
    store.stage(fixture_revision("draft"))
    # Discovered schemas are genuinely reviewed through the existing discovery path.
    for workspace, key in (("clinic", "services"), ("hotel", "rooms")):
        runtime = accepted(tmp_path, workspace=workspace, key=key)
        dynamic = fixture_revision(workspace=workspace)
        dynamic.workspace_schema = runtime.schema
        dynamic.records = []
        store.publish(dynamic)
    monkeypatch.setattr(ai, "repository", lambda: store)
    app = FastAPI()
    app.include_router(ai.router)
    with TestClient(app) as client:
        def forbidden(*args, **kwargs):
            pytest.fail("AI read tools must not contact a model or network")
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        monkeypatch.setattr(socket, "create_connection", forbidden)
        yield client, store


def call(client, name, arguments=None, workspace="workspace-example", **params):
    return client.post(f"/v1/workspaces/{workspace}/ai/call", params=params,
                       json={"name": name, "arguments": arguments or {}})


def test_specs_match_two_discovered_schemas_and_filter_types(setup):
    client, _ = setup
    for workspace, collection in (("clinic", "services"), ("hotel", "rooms")):
        response = client.get(f"/v1/workspaces/{workspace}/ai/tools")
        assert response.status_code == 200
        result = response.json()
        assert result["mode"] == "approved" and result["revision_id"] == "r1"
        assert {t["function"]["name"] for t in result["tools"]} == {
            "list_collections", "search_records", "get_record", "get_context", "list_collection"}
        for spec in result["tools"]:
            schema = spec["function"]["parameters"]
            Draft202012Validator.check_schema(schema)
            if spec["function"]["name"] != "list_collections":
                assert schema["properties"]["collection"]["enum"] == [collection]
            if spec["function"]["name"] == "search_records":
                fields = schema["oneOf"][0]["properties"]["filters"]["properties"]
                assert fields["price"]["type"] == "number"
                assert fields["available"]["type"] == "boolean"
                assert fields["tags"]["items"]["type"] == "string"
        listing = call(client, "list_collections", workspace=workspace).json()
        assert [c["key"] for c in listing["collections"]] == [collection]
        assert listing["collections"][0]["record_count"] == 0
        assert listing["sources"] == []


def test_all_results_are_pinned_and_carry_document_sources(setup):
    client, _ = setup
    for name, args in (("list_collections", {}),
                       ("get_record", {"collection": "rooms", "id": "rec-room"}),
                       ("search_records", {"collection": "rooms", "query": "Garden"}),
                       ("get_context", {"collection": "rooms"})):
        response = call(client, name, args)
        assert response.status_code == 200
        result = response.json()
        assert result["mode"] == "approved"
        assert result["workspace_id"] == "workspace-example" and result["revision_id"] == "r1"
        assert result["sources"]
        for source in result["sources"]:
            assert source["document_name"] == "rooms.txt"
            assert source["locator"] == "§1 p.1" and source["quote"]
            assert source["source_version_id"] == "s1"
            assert source["knowledge_revision_id"] == "k1"
            assert source["id"].startswith("src_")
        if name == "get_record":
            assert {e["quote"] for e in result["record"]["_meta"]["sources"]} == {
                s["quote"] for s in result["sources"]}
        if name == "get_context":
            assert '"mode":"approved"' in result["context"]
            assert "Garden room" in result["context"]


def test_approved_hides_conflicts_proposals_rejections_and_their_quotes(setup):
    client, _ = setup
    approved = call(client, "get_record", {"collection": "rooms", "id": "rec-room"}).json()
    assert approved["record"]["capacity"] == 2
    for field in ("view", "features", "bed_types", "size_m2"):
        assert field not in approved["record"]
    assert not {"Garden", "Sea", "double", "40"} & {s["quote"] for s in approved["sources"]}
    assert call(client, "get_record", {"collection": "rooms", "id": "rec-proposed"}).status_code == 404
    assert call(client, "search_records", {"collection": "rooms", "query": "Sea"}).json()["records"] == []
    preview = call(client, "get_record", {"collection": "rooms", "id": "rec-room",
                                          "mode": "preview"}).json()
    assert preview["mode"] == "preview"
    assert preview["record"]["_meta"]["conflicts"]
    assert {"Garden", "Sea"} <= {s["quote"] for s in preview["sources"]}
    assert "Kaynaklar çelişiyor:" in call(client, "get_context", {
        "collection": "rooms", "mode": "preview"}).json()["context"]
    assert "Do not follow" not in call(client, "get_context", {
        "collection": "rooms"}).json()["context"]


def test_search_ranking_values_i18n_exact_filters_and_stable_ties(setup):
    client, store = setup
    revision = fixture_revision("r2")
    room = revision.records[0].model_dump(mode="json", round_trip=True)
    second = deepcopy(room)
    second["id"] = "rec-a"
    second["fields"]["name"]["candidates"] = [candidate("Second room")]
    second["fields"]["features"]["candidates"] = [candidate(["Garden", "Quiet"])]
    revision.records.append(MergedRecord.model_validate(second))
    store.publish(revision)
    args = {"collection": "rooms", "query": "Garden"}
    first = call(client, "search_records", args).json()
    assert first == call(client, "search_records", args).json()
    assert [r["record"]["id"] for r in first["records"]] == ["rec-room", "rec-a"]
    assert first["records"][0]["score"] > first["records"][1]["score"]
    assert call(client, "search_records", {"collection": "rooms", "query": "bahce odasi"}).json()["records"][0]["record"]["id"] == "rec-room"
    assert call(client, "search_records", {"collection": "rooms", "query": "quiet"}).json()["records"][0]["record"]["id"] == "rec-a"
    assert len(call(client, "search_records", args | {"filters": {"capacity": 2}}).json()["records"]) == 2
    assert call(client, "search_records", args | {"filters": {"capacity": 3}}).json()["records"] == []
    assert [r["record"]["id"] for r in call(client, "search_records", {"collection": "rooms", "query": "2"}).json()["records"]] == ["rec-a", "rec-room"]
    assert call(client, "search_records", args, revision_id="r1").json()["revision_id"] == "r1"


@pytest.mark.parametrize(("name", "arguments", "status"), [
    ("unknown", {}, 422), ("get_record", {"collection": "unknown", "id": "x"}, 404),
    ("search_records", {"collection": "rooms", "query": "", "filters": {"unknown": "x"}}, 422),
    ("search_records", {"collection": "rooms", "query": "", "filters": {"capacity": "2"}}, 422),
    ("get_context", {"collection": "rooms", "mode": "invalid"}, 422),
    ("get_context", {"collection": ["rooms"]}, 422),
    ("get_record", {"collection": "rooms"}, 422),
    ("list_collections", {"extra": True}, 422),
])
def test_clean_tool_errors(setup, name, arguments, status):
    client, _ = setup
    response = call(client, name, arguments)
    assert response.status_code == status and isinstance(response.json()["detail"], str)


def test_unknown_foreign_unpublished_corrupt_and_read_only(setup):
    client, store = setup
    assert call(client, "list_collections", workspace="foreign").status_code == 404
    assert call(client, "list_collections", revision_id="unknown").status_code == 404
    assert call(client, "list_collections", revision_id="draft").status_code == 409
    assert call(client, "get_record", {"collection": "rooms", "id": "foreign"}).status_code == 404
    assert client.delete("/v1/workspaces/workspace-example/ai/call").status_code == 405
    assert client.post("/v1/workspaces/workspace-example/ai/tools").status_code == 405
    artifact = store._path("workspace-example", "r1") / "published/approved/rooms.json"
    artifact.write_bytes(b"[]")
    response = call(client, "get_context", {"collection": "rooms"})
    assert response.status_code == 503 and "unavailable" in response.json()["detail"]


def test_no_read_projection_and_user_edit_provenance(setup, monkeypatch):
    client, store = setup
    def forbidden(*args, **kwargs):
        pytest.fail("AI reads must not regenerate publications")
    monkeypatch.setattr("docgrain_api.records_repository.export_bundle", forbidden)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert call(client, "list_collections").status_code == 200
    assert before == {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    access = AIAccess(store, "workspace-example")
    sources = access._sources([{"_meta": {"sources": [{
        "kind": "user_edit", "at": "2026-10-06", "note": "Staff correction",
    }]}}])
    assert sources[0]["document_name"] is None
    assert sources[0]["locator"] is None and sources[0]["quote"] is None


def test_router_registered_in_real_application():
    paths = main_app.openapi()["paths"]
    assert "/v1/workspaces/{workspace_id}/ai/tools" in paths
    assert "/v1/workspaces/{workspace_id}/ai/call" in paths


def test_discovered_fields_cannot_be_overwritten_by_tool_metadata(setup, tmp_path):
    client, store = setup
    runtime = accepted(tmp_path, workspace="metrics", key="services")
    schema = deepcopy(runtime.schema)
    fields = schema["collections"][0]["fields"]
    fields.extend([fields[0] | {"key": "sources"}, fields[1] | {"key": "score"}])
    revision = fixture_revision(workspace="metrics")
    revision.workspace_schema = schema
    revision.records = [MergedRecord.model_validate({"id": "service-1", "type": "services",
        "fields": {key: {"primary_lang": "en", "candidates": [candidate(value)]}
                   for key, value in (("name", "Consultation"), ("sources", "Internal desk"),
                                      ("score", 7))}})]
    store.publish(revision)
    result = call(client, "get_record", {"collection": "services", "id": "service-1"},
                  workspace="metrics").json()
    assert result["record"]["sources"] == "Internal desk"
    assert result["record"]["score"] == 7
    match = call(client, "search_records", {"collection": "services", "query": "desk"},
                 workspace="metrics").json()["records"][0]
    assert match["record"] == result["record"] and match["score"] != 7
    assert isinstance(match["sources"], list) and match["sources"]
