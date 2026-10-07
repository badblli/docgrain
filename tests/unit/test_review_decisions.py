"""Synthetic workspace questions exercise actual immutable preview/approved publications."""

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from docgrain_api.records_repository import QuestionStale, RecordsRepository
from docgrain_api.routers import records
from docgrain_records.export import export_bundle
from docgrain_records.merge_models import FactCandidate, MergedField, MergeRevision
from docgrain_records.review import CandidateAnswer, questions, summary
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_records_export import candidate, fixture_revision
from test_schema_driven_records import accepted

BASE = "/v1/workspaces/workspace-example"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = RecordsRepository(tmp_path / "packs")
    store.publish(fixture_revision())
    monkeypatch.setattr(records, "repository", lambda: store)
    app = FastAPI()
    app.include_router(records.router)
    app.include_router(records.workspace_router)
    with TestClient(app) as client:
        def forbidden(*args, **kwargs):
            pytest.fail("review decisions must not call network or models")
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        monkeypatch.setattr(socket, "create_connection", forbidden)
        yield client, store


def answer(client, question, body, suffix=""):
    return client.post(BASE + f"/questions/{question['id']}/answer" + suffix, json=body)


def assert_evidenced(client, revision):
    for mode in ("preview", "approved"):
        rows = client.get(BASE + f"/revisions/{revision}/collections/rooms?mode={mode}").json()
        for row in rows:
            for metadata in row["_meta"]["fields"].values():
                for evidence in metadata["i18n"].values():
                    assert evidence
                    assert all(e.get("quote") or e.get("kind") == "user_edit" for e in evidence)
    assert client.get(BASE + "/summary").json()["unsupported_fields"] == 0


def test_summary_counts_published_fields_and_questions(setup):
    client, _ = setup
    result = client.get(BASE + "/summary").json()
    assert set(result) == {"workspace_id", "revision_id", "documents", "records",
                           "unsupported_fields", "conflicts", "needs_review", "accepted_ratio",
                           "updated_at", "collections", "duplicates"}
    assert result["workspace_id"] == "workspace-example" and result["revision_id"] == "r1"
    assert result["documents"] == 1 and result["records"] == 2
    assert result["conflicts"] == result["needs_review"] == 1
    assert result["unsupported_fields"] == 0
    assert result["accepted_ratio"] == pytest.approx(3 / 7)
    rooms = next(c for c in result["collections"] if c["key"] == "rooms")
    assert rooms == {"key": "rooms", "label": "rooms", "records": 2,
                     "conflicts": 1, "needs_review": 1,
                     "accepted_records": 0, "pending_records": 1, "duplicates": 0}
    assert next(c for c in result["collections"] if c["key"] == "outlets")["records"] == 0
    assert result["updated_at"]


def test_questions_exact_contract_order_pagination_and_stability(setup):
    client, store = setup
    result = client.get(BASE + "/questions").json()
    assert result["total"] == 2
    assert [q["kind"] for q in result["items"]] == ["conflict", "needs_review"]
    conflict, pending = result["items"]
    assert set(conflict) == {"id", "kind", "collection", "collection_label", "record_id",
                             "record_title", "field", "field_label", "lang", "options", "allow_all"}
    assert conflict["collection"] == "rooms" and conflict["record_title"] == "Bahçe odası"
    assert conflict["field"] == "view" and conflict["lang"] == "en"
    assert conflict["options"] == [
        {"candidate_id": "view-a", "value": "Garden", "display": "Garden", "quote": "Garden",
         "document_id": "doc-example", "document_name": "doc-example", "locator": "s. 1"},
        {"candidate_id": "view-b", "value": "Sea", "display": "Sea", "quote": "Sea",
         "document_id": "doc-example", "document_name": "doc-example", "locator": "s. 1"},
    ]
    assert pending["options"][0]["value"] == ["double"]
    assert client.get(BASE + "/questions?limit=1&offset=1").json() == {
        "total": 2, "items": [pending]}
    assert client.get(BASE + "/questions?offset=20").json() == {"total": 2, "items": []}
    assert RecordsRepository(store.root).list_questions("workspace-example")["items"] == result["items"]
    revision = store._source("workspace-example")
    revision.records.reverse()
    for record in revision.records:
        for field in record.fields.values():
            field.candidates.reverse()
    assert questions(revision) == result["items"]


def test_candidate_answer_publishes_approved_value_history_and_keeps_old_bytes(setup):
    client, store = setup
    old_path = store._path("workspace-example", "r1")
    before = {p.relative_to(old_path): p.read_bytes() for p in old_path.rglob("*") if p.is_file()}
    conflict, pending = client.get(BASE + "/questions").json()["items"]
    response = answer(client, conflict, {"candidate_id": "view-b"})
    assert response.status_code == 200
    result = response.json()
    assert set(result) == {"revision_id", "remaining"} and result["remaining"] == 1
    revision = result["revision_id"]
    row = client.get(BASE + f"/revisions/{revision}/collections/rooms?mode=approved").json()[0]
    assert row["view"] == "Sea" and row["capacity"] == 2
    assert row["_meta"]["fields"]["view"]["evidence"][0]["quote"] == "Sea"
    source = store._source("workspace-example")
    assert source.parent_id == source.lineage_id == "r1"
    assert [c.review_state for c in source.records[0].fields["view"].candidates] == [
        "rejected", "accepted"]
    assert source.history[0].actor == "local" and source.history[0].question_id == conflict["id"]
    assert source.history[0].candidate_id == "view-b"
    assert all((old_path / name).read_bytes() == body for name, body in before.items())
    assert "view" not in client.get(BASE + "/revisions/r1/collections/rooms?mode=approved").json()[0]
    assert client.get(BASE + "/summary?revision_id=r1").json()["conflicts"] == 1
    assert client.get(BASE + "/summary").json()["accepted_ratio"] == pytest.approx(4 / 7)
    # Unanswered questions keep their ID across a child revision.
    assert client.get(BASE + "/questions").json()["items"] == [pending]
    assert_evidenced(client, revision)


def test_typed_edit_user_authority_preserves_source_quotes_and_chained_history(setup):
    client, store = setup
    conflict, pending = client.get(BASE + "/questions").json()["items"]
    result = answer(client, conflict, {"value": "Courtyard", "note": "Yerinde kontrol edildi."}).json()
    first = result["revision_id"]
    source = store._source("workspace-example")
    candidates = source.records[0].fields["view"].candidates
    assert [c.review_state for c in candidates] == ["rejected", "rejected", "accepted"]
    assert [c.evidence[0].quote for c in candidates[:2]] == ["Garden", "Sea"]
    evidence = candidates[-1].evidence[0].model_dump()
    assert evidence == {"kind": "user_edit", "at": source.updated_at, "note": "Yerinde kontrol edildi."}
    assert "quote" not in evidence
    row = client.get(BASE + f"/revisions/{first}/collections/rooms?mode=approved").json()[0]
    assert row["view"] == "Courtyard"
    assert row["_meta"]["fields"]["view"]["evidence"] == [evidence]
    assert "Sizin düzeltmeniz:" in client.get(
        BASE + f"/revisions/{first}/collections/rooms/context?mode=approved").text
    assert_evidenced(client, first)
    client.get(BASE + "/questions")
    second = answer(client, pending, {"value": ["queen"], "note": ""}).json()["revision_id"]
    source = store._source("workspace-example")
    assert source.parent_id == first and source.lineage_id == "r1" and len(source.history) == 2
    assert client.get(BASE + "/questions").json() == {"total": 0, "items": []}
    assert client.get(BASE + f"/revisions/{first}/collections/rooms?mode=approved").json()[0]["view"] == "Courtyard"
    assert_evidenced(client, second)


def test_skip_only_reorders_within_kind_and_survives_restart_and_answer(setup):
    client, store = setup
    revision = fixture_revision("r2")
    revision.records[0].fields["capacity"] = MergedField(primary_lang="en", candidates=[
        FactCandidate.model_validate(candidate(2, "needs_review", id="capacity-a")),
        FactCandidate.model_validate(candidate(3, "needs_review", id="capacity-b")),
    ])
    revision.records[0].fields["features"].candidates[0].review_state = "needs_review"
    store.publish(revision)
    items = client.get(BASE + "/questions").json()["items"]
    assert [q["field"] for q in items] == ["capacity", "view", "bed_types", "features"]
    summary_before = client.get(BASE + "/summary").json()
    assert answer(client, items[0], {"skip": True}).json() == {"revision_id": "r2", "remaining": 4}
    assert store.list_revisions("workspace-example") == ["r2", "r1"]
    assert client.get(BASE + "/summary").json() == summary_before
    assert_evidenced(client, "r2")
    reordered = RecordsRepository(store.root).list_questions("workspace-example")["items"]
    assert reordered == [items[1], items[0], items[2], items[3]]
    assert answer(client, items[2], {"skip": True}).status_code == 200
    assert client.get(BASE + "/questions").json()["items"] == [items[1], items[0], items[3], items[2]]
    assert answer(client, items[1], {"candidate_id": "view-a"}).status_code == 200
    assert client.get(BASE + "/questions").json()["items"] == [items[0], items[3], items[2]]


@pytest.mark.parametrize("body", [{"skip": True}, {"all": True}, {"candidate_id": "fact-a"},
                                 {"document_id": "doc-example"},
                                 {"value": ["queen"], "note": "checked"}])
def test_stale_revision_returns_409_including_skip_and_pinned_answers(setup, body):
    client, store = setup
    conflict, pending = client.get(BASE + "/questions").json()["items"]
    assert answer(client, conflict, {"candidate_id": "view-a"}).status_code == 200
    assert answer(client, pending, body).status_code == 409
    # Explicit revision binding remains stale even after another reader refreshes the stable ID.
    client.get(BASE + "/questions")
    assert answer(client, pending, body, "?revision_id=r1").status_code == 409
    assert len(store.list_revisions("workspace-example")) == 2


def test_external_publication_invalidates_served_questions(setup):
    client, store = setup
    conflict = client.get(BASE + "/questions").json()["items"][0]
    store.publish(fixture_revision("external"))
    assert answer(client, conflict, {"candidate_id": "view-a"}).status_code == 409


def test_concurrent_answers_from_separate_repository_instances_have_one_winner(setup):
    client, store = setup
    conflict, pending = client.get(BASE + "/questions").json()["items"]
    gate = Barrier(2)

    def submit(question):
        instance = RecordsRepository(store.root)
        gate.wait(timeout=10)
        try:
            return instance.answer_question("workspace-example", question["id"],
                                            CandidateAnswer(candidate_id=question["options"][0]["candidate_id"]))
        except QuestionStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [conflict, pending]))
    assert results.count("stale") == 1
    assert len(store.list_revisions("workspace-example")) == 2
    assert client.get(BASE + "/questions").json()["total"] == 1
    assert_evidenced(client, store.list_revisions("workspace-example")[0])


@pytest.mark.parametrize("body", [{}, {"skip": False}, {"skip": 1},
                                 {"same": True}, {"same": False},
                                 {"document_id": "unknown"}, {"document_id": ""},
                                 {"document_id": None},
                                 {"document_id": "doc-example", "all": True},
                                 {"document_id": "doc-example", "candidate_id": "view-a"},
                                 {"all": False}, {"all": 1}, {"all": "true"},
                                 {"all": True, "candidate_id": "view-a"},
                                 {"candidate_id": "view-a", "skip": True},
                                 {"candidate_id": "view-a", "note": "extra"},
                                 {"value": "Sea"}, {"candidate_id": None},
                                 {"candidate_id": "fact-a"},
                                 {"value": "Sea", "note": "ok", "field": "new"},
                                 {"value": None, "note": ""},
                                 {"value": 4, "note": ""},
                                 {"value": ["Sea"], "note": ""}])
def test_invalid_or_mixed_answer_never_publishes(setup, body):
    client, store = setup
    conflict = client.get(BASE + "/questions").json()["items"][0]
    assert answer(client, conflict, body).status_code == 422
    assert store.list_revisions("workspace-example") == ["r1"]


@pytest.mark.parametrize("suffix", ["/summary", "/questions"])
def test_revision_workspace_and_pagination_boundaries(setup, suffix):
    client, store = setup
    store.stage(fixture_revision("draft"))
    store.publish(fixture_revision("foreign", workspace="other-workspace"))
    assert client.get(BASE + suffix + "?revision_id=draft").status_code == 409
    assert client.get(BASE + suffix + "?revision_id=foreign").status_code == 404
    assert client.get(BASE.replace("workspace-example", "unknown") + suffix).status_code == 404
    assert client.get(BASE + suffix + "?revision_id=missing").status_code == 404
    assert client.get(BASE + "/questions?limit=0").status_code == 422
    assert client.get(BASE + "/questions?offset=-1").status_code == 422
    assert client.post(BASE + "/questions/unknown/answer", json={"skip": True}).status_code == 404


def test_empty_summary_and_no_evidence_models_fail_closed(setup):
    client, store = setup
    empty = fixture_revision("empty")
    empty.records = []
    store.publish(empty)
    result = client.get(BASE + "/summary").json()
    assert result["records"] == result["conflicts"] == result["needs_review"] == 0
    assert result["accepted_ratio"] == 0 and result["unsupported_fields"] == 0
    assert client.get(BASE + "/questions").json() == {"total": 0, "items": []}
    unsupported = candidate("Sea")
    unsupported["evidence"] = []
    with pytest.raises(ValidationError):
        FactCandidate.model_validate(unsupported)
    unsupported["evidence"] = [{"kind": "user_edit", "note": "Missing timestamp"}]
    with pytest.raises(ValidationError):
        FactCandidate.model_validate(unsupported)


def test_dynamic_schema_turkish_labels_typed_edit_and_language_isolation(tmp_path, monkeypatch):
    runtime = accepted(tmp_path, "workspace-example", "services", "title")
    schema = runtime.schema
    collection = schema["collections"][0]
    collection["label_i18n"].append({"lang": "tr", "value": "Hizmetler"})
    collection["fields"][1]["label_i18n"].append({"lang": "tr", "value": "Ücret"})
    revision = MergeRevision.model_validate({
        "workspace_id": "workspace-example", "id": "dynamic", "workspace_schema": schema,
        "documents": [{"document_id": "doc-example", "document_name": "Hizmet listesi",
                       "source_version_id": "s1", "knowledge_revision_id": "k1"}],
        "records": [{"id": "service", "type": "services", "fields": {
            "title": {"primary_lang": "en", "candidates": [candidate("Consultation")]},
            "price": {"primary_lang": "en", "candidates": [
                candidate(40, "needs_review", id="price-a"),
                candidate(45, "needs_review", id="price-b"),
                candidate(50, "needs_review", lang="tr", id="price-tr")
            ]},
        }}],
    })
    store = RecordsRepository(tmp_path / "packs")
    store.publish(revision)
    monkeypatch.setattr(records, "repository", lambda: store)
    app = FastAPI()
    app.include_router(records.workspace_router)
    with TestClient(app) as client:
        items = client.get(BASE + "/questions").json()["items"]
        assert [q["kind"] for q in items] == ["conflict", "needs_review"]
        assert items[0]["collection_label"] == "Hizmetler" and items[0]["field_label"] == "Ücret"
        assert items[0]["record_title"] == "Consultation"
        assert items[0]["options"][0]["document_name"] == "Hizmet listesi"
        assert answer(client, items[0], {"value": "wrong type", "note": ""}).status_code == 422
        assert answer(client, items[0], {"value": 42, "note": "confirmed"}).status_code == 200
        result = store._source("workspace-example")
        assert result.records[0].fields["price"].candidates[2].review_state == "needs_review"
        assert client.get(BASE + "/questions").json()["items"] == [items[1]]
        approved = json.loads(export_bundle(result, "approved")["services.json"])[0]
        assert approved["price"] == 42 and "tr" not in approved["i18n"]
        assert summary(result, "unused")["accepted_ratio"] == pytest.approx(2 / 3)
        assert client.get(BASE + "/summary").json()["unsupported_fields"] == 0


def test_failed_publication_does_not_change_newest_or_old_revision(setup, monkeypatch):
    client, store = setup
    question = client.get(BASE + "/questions").json()["items"][0]
    before = client.get(BASE + "/revisions/r1/collections/rooms").content

    def fail(*args, **kwargs):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr("docgrain_api.records_repository.export_bundle", fail)
    assert answer(client, question, {"candidate_id": "view-a"}).status_code == 503
    assert store.list_revisions("workspace-example") == ["r1"]
    assert client.get(BASE + "/revisions/r1/collections/rooms").content == before
