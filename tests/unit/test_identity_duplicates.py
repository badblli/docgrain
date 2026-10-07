"""Synthetic FAQ and suite variants exercise acceptance, questions and publication."""

import json
import socket
from copy import deepcopy

import httpx
import pytest
from docgrain_api.records_repository import RecordsRepository
from docgrain_api.routers import records as routes
from docgrain_records.discovery import verify_discovery
from docgrain_records.discovery_store import accept_schema, write_proposal
from docgrain_records.duplicates import normalized_name
from docgrain_records.export import export_bundle, load_revision, project_records
from docgrain_records.merge import JsonMergeStore
from docgrain_records.merge_models import (
    FactCandidate,
    MergedField,
    MergedRecord,
    MergeRevision,
)
from docgrain_records.review import (
    CandidateAnswer,
    DuplicateAnswer,
    answer_revision,
    questions,
    summary,
)
from docgrain_records.runtime import HOSPITALITY, RuntimeRecords
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_schema_driven_records import fact, source


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("identity and duplicate review must remain offline")
    # Windows' asyncio loop uses a local socket pair during TestClient startup.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def accept_fields(tmp_path, keys):
    doc = source("example", "doc-faq", "[§1 p.1]\nEvet var. Otopark var mı?\n")
    values = {key: "Evet var." if key == "answer" else "Otopark var mı?" for key in keys}
    labels = [{"lang": "en", "value": "FAQs"}, {"lang": "tr", "value": "Sorular"}]
    proposal = verify_discovery(json.dumps({"collections": [{
        "key": "faqs", "description": "Company questions.", "label_i18n": labels,
        "fields": [{"key": key, "type": "string", "unit": None, "label_i18n": labels}
                   for key in keys],
        "examples": [{"values": [{"key": key, **fact("doc-faq", values[key])}
                                 for key in keys]}],
    }]}), [doc], "example")
    write_proposal(tmp_path, proposal, [doc])
    for collection in proposal.collections:
        collection.review_state = "accepted"
        for field in collection.fields:
            field.review_state = "accepted"
    path = tmp_path / "schema.proposed.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    return accept_schema(path, tmp_path)


@pytest.mark.parametrize(("keys", "expected"), [
    (["answer", "question"], "question"),
    (["answer", "label", "term", "question", "title", "name"], "name"),
    (["answer", "label", "term", "question", "title"], "title"),
    (["answer", "label", "term"], "term"),
    (["answer", "label"], "label"),
    (["answer", "detail"], "answer"),
])
def test_schema_acceptance_pins_identity_priority_and_legacy_fallback(tmp_path, keys, expected):
    schema = accept_fields(tmp_path, keys)
    assert schema.collections[0].identity == expected
    stored = json.loads((tmp_path / "schema.v1.json").read_text(encoding="utf-8"))
    assert stored["collections"][0]["identity"] == expected
    assert RuntimeRecords(stored).identities["faqs"] == expected
    del stored["collections"][0]["identity"]
    assert RuntimeRecords(stored).identities["faqs"] == ("name" if "name" in keys else keys[0])
    stored["collections"][0]["identity"] = "absent"
    with pytest.raises(ValidationError, match="identity must"):
        RuntimeRecords(stored)


def merged_fact(value, key, document="doc-faq", state="proposed"):
    return FactCandidate(id=f"{document}-{key}", value=value, lang="en", review_state=state,
                         evidence=[{"document_id": document, "source_version_id": document + "-v1",
                                    "knowledge_revision_id": document + "-k1",
                                    "locator": "§1 p.1", "quote": str(value)}])


def test_faq_question_and_export_title_use_question_not_answer(tmp_path):
    schema = accept_fields(tmp_path, ["answer", "question"])
    revision = MergeRevision(workspace_id="example", id="faq-r1", workspace_schema=schema.model_dump(),
                             documents=[{"document_id": "doc-faq", "source_version_id": "doc-faq-v1",
                                         "knowledge_revision_id": "doc-faq-k1"}],
                             records=[MergedRecord(id="faq-1", type="faqs", fields={
                                 key: MergedField(primary_lang="en", candidates=[
                                     merged_fact(value, key, state="needs_review" if key == "answer"
                                                 else "proposed")])
                                 for key, value in {"answer": "Evet var.",
                                                    "question": "Otopark var mı?"}.items()})])
    legacy = revision.model_copy(deep=True)
    del legacy.workspace_schema["collections"][0]["identity"]
    assert questions(legacy)[0]["record_title"] == "Evet var."
    assert questions(revision)[0]["record_title"] == "Otopark var mı?"
    assert project_records(revision)["faqs"][0]["_meta"]["identity"] == "question"
    runtime = RuntimeRecords(schema)
    document = runtime.merge_document({
        "workspace_id": "example", "document_id": "doc-faq", "source_version_id": "doc-faq-v1",
        "knowledge_revision_id": "doc-faq-k1", "context": "[§1 p.1]\nOtopark var mı? Evet var.",
        "records": [{"source_identity": "faq-1", "record": {
            "id": "faq-1", "type": "faqs", "answer": fact("doc-faq", "Evet var."),
            "question": fact("doc-faq", "Otopark var mı?")}}],
    })
    assert document.records[0].record.name.value == "Otopark var mı?"
    merged = JsonMergeStore(tmp_path / "faq-merge.json", "example").merge(
        "faq-merged", [document], runtime=runtime)
    assert merged.records[0].fields["question"].candidates[0].value == "Otopark var mı?"


def room_revision(tmp_path, names=None):
    names = names or ["Cedar Suite", "Cedar Suit Oda", "Maple Suit", "Maple Suite", "Maple Suit Oda"]
    docs = []
    for index, name in enumerate(names):
        document = f"doc-{index}"
        values = {"name": name, "capacity": 4, "size_m2": 60.0,
                  "view": "Garden" if index % 2 == 0 else "Sea"}
        docs.append(HOSPITALITY.merge_document({
            "workspace_id": "example", "document_id": document, "source_version_id": document + "-v1",
            "knowledge_revision_id": document + "-k1", "document_name": f"Örnek belge {index + 1}",
            "context": "[§1 p.1]\n" + " ".join(str(v) for v in values.values()),
            "records": [{"source_identity": f"room-{index}", "record": {
                "id": f"source-{index}", "type": "room_type",
                **{key: fact(document, value) for key, value in values.items()}}}],
        }))
    return JsonMergeStore(tmp_path / "rooms-merge.json", "example").merge("r1", docs)


def duplicates(revision):
    return [q for q in questions(revision) if q["kind"] == "duplicate"]


def test_finding_five_variants_stay_separate_and_produce_four_evidenced_pairs(tmp_path):
    revision = room_revision(tmp_path)
    assert len(revision.records) == 5
    pairs = duplicates(revision)
    assert len(pairs) == 4  # one pair plus the three edges of the second group
    assert all(q["question_tr"] == "Bu iki kayıt aynı mı?" for q in pairs)
    for question in pairs:
        assert len(question["duplicate_records"]) == 2
        assert len(set(question["record_ids"])) == 2
        for card in question["duplicate_records"]:
            assert len(card["fields"]) == 3 and card["title"]
            assert card["sources"] and all(s["quote"] for s in card["sources"])
            assert all(s["document_name"].startswith("Örnek belge") for s in card["sources"])
    before = deepcopy(pairs)
    revision.records.reverse()
    for record in revision.records:
        for field in record.fields.values():
            field.candidates.reverse()
    assert duplicates(revision) == before
    result = summary(revision, "now")
    assert result["duplicates"] == 4 and result["conflicts"] == 0
    rooms = next(c for c in result["collections"] if c["key"] == "rooms")
    assert rooms["duplicates"] == 4 and rooms["pending_records"] == 5


@pytest.mark.parametrize(("left", "right"), [
    ("Çınar İŞIK Suit Oda", "isik cinar Suite"),
    ("Cedar Garden Suite", "garden CEDAR room"),
])
def test_name_normalization_turkish_case_stop_words_and_token_sort(left, right):
    assert normalized_name(left) == normalized_name(right)


def test_conservative_scoring_needs_distinctive_names_and_field_overlap(tmp_path):
    revision = room_revision(tmp_path, ["Cedar Suite", "Cedar Suit Oda"])
    assert len(duplicates(revision)) == 1
    for record in revision.records:
        record.fields = {"name": record.fields["name"]}
    assert not duplicates(revision)
    generic = room_revision(tmp_path / "generic", ["Suite", "Suit Oda"])
    assert not duplicates(generic)


def test_near_names_need_two_matching_fields_and_do_not_match_other_room(tmp_path):
    revision = room_revision(tmp_path, ["Cedar Garden Suite", "Cedar Gardens Suit Oda", "Maple Suite"])
    pairs = duplicates(revision)
    assert len(pairs) == 1
    assert "Maple" not in pairs[0]["record_title"]
    for record in revision.records:
        record.fields.pop("size_m2")
    assert not duplicates(revision)


def test_different_pair_is_remembered_after_another_merge_and_restart(tmp_path):
    base = room_revision(tmp_path, ["Maple Suit", "Maple Suite", "Maple Suit Oda"])
    question = duplicates(base)[0]
    revised = answer_revision(base, question["id"], DuplicateAnswer(same=False))
    assert len(duplicates(revised)) == 2
    other = duplicates(revised)[0]
    consolidated = answer_revision(revised, other["id"], DuplicateAnswer(same=True))
    assert len(consolidated.records) == 2
    assert not duplicates(consolidated)
    reloaded = load_revision(consolidated.model_dump_json(round_trip=True).encode())
    assert not duplicates(reloaded)
    different = next(d for d in reloaded.duplicate_decisions if not d.same)
    assert set(different.record_ids) == {r.id for r in reloaded.records}


def test_different_decision_survives_new_ingestion_lineage_and_staging_retries(tmp_path):
    store = RecordsRepository(tmp_path / "packs")
    base = room_revision(tmp_path, ["Cedar Suite", "Cedar Suit Oda"])
    store.publish(base)
    question = store.list_questions("example")["items"][0]
    store.answer_question("example", question["id"], DuplicateAnswer(same=False))
    fresh = base.model_copy(deep=True)
    fresh.id = "new-ingestion"
    assert fresh.parent_id is None and not fresh.duplicate_decisions
    store.stage(fresh)
    store.publish(fresh)
    store.publish(fresh)  # Idempotent even though the caller did not supply inherited vetoes.
    assert not fresh.duplicate_decisions  # Publication never mutates the caller.
    restarted = RecordsRepository(store.root)
    assert restarted.list_questions("example")["total"] == 0
    assert restarted.workspace_summary("example")["duplicates"] == 0
    assert restarted.workspace_summary("example", "r1")["duplicates"] == 1
    assert len(restarted._source("example", "new-ingestion").records) == 2
    assert len(restarted._source("example", "new-ingestion").duplicate_decisions) == 1


def test_identity_conflict_and_duplicate_have_safe_order_and_exclusive_summary_counts(tmp_path):
    base = room_revision(tmp_path, ["Cedar Suite", "Cedar Suit Oda"])
    record = base.records[0]
    other_name = record.fields["name"].candidates[0].model_copy(deep=True)
    other_name.id += "-other"
    other_name.value = "Cedar Room"
    record.fields["name"].candidates.append(other_name)
    pending = questions(base)
    assert [q["kind"] for q in pending] == ["conflict", "duplicate"]
    # Both records can have approved fields while their identity still awaits review.
    record.fields["name"].candidates.pop()
    for record in base.records:
        for field in record.fields.values():
            for candidate in field.candidates:
                candidate.review_state = "accepted"
    rooms = next(c for c in summary(base, "now")["collections"] if c["key"] == "rooms")
    assert rooms["accepted_records"] == 0 and rooms["pending_records"] == 2


def test_merge_unions_fields_evidence_and_reopens_previously_accepted_conflicts(tmp_path):
    base = room_revision(tmp_path, ["Cedar Suite", "Cedar Suit Oda"])
    for record in base.records:
        for field in record.fields.values():
            for candidate in field.candidates:
                candidate.review_state = "accepted"
    question = duplicates(base)[0]
    retired = next(r for r in base.records if r.id == question["record_ids"][1])
    retired.fields["bed_types"] = MergedField(primary_lang="en", candidates=[
        merged_fact(["queen"], "bed_types", document=base.documents[1].document_id)])
    before = base.model_dump_json(round_trip=True)
    revised = answer_revision(base, question["id"], DuplicateAnswer(same=True))
    assert len(revised.records) == 1 and not duplicates(revised)
    assert revised.parent_id == revised.lineage_id == base.id
    assert revised.duplicate_decisions[0].same is True
    record = revised.records[0]
    assert record.id == question["record_ids"][0] and "bed_types" in record.fields
    capacity = record.fields["capacity"].candidates
    assert len(capacity) == 1 and len(capacity[0].evidence) == 2
    pending = questions(revised)
    assert {(q["kind"], q["field"]) for q in pending} == {("conflict", "name"), ("conflict", "view")}
    rows = json.loads(export_bundle(revised, "approved")["rooms.json"])
    assert rows[0]["capacity"] == 4 and "name" not in rows[0] and "view" not in rows[0]
    assert summary(revised, "now")["unsupported_fields"] == 0
    resolved = answer_revision(revised, pending[0]["id"], CandidateAnswer(
        candidate_id=pending[0]["options"][0]["candidate_id"]))
    assert len(questions(resolved)) == 1
    assert load_revision(revised.model_dump_json(round_trip=True).encode()).duplicate_decisions[0].same
    assert before == base.model_dump_json(round_trip=True)
    assert len(base.records) == 2 and all(c.review_state == "accepted"
                                       for c in base.records[0].fields["name"].candidates)


@pytest.mark.parametrize("same", [True, False])
def test_duplicate_api_publishes_immutable_revision_and_remembers_answer(tmp_path, monkeypatch, same):
    store = RecordsRepository(tmp_path / "packs")
    base = room_revision(tmp_path, ["Cedar Suite", "Cedar Suit Oda"])
    store.publish(base)
    monkeypatch.setattr(routes, "repository", lambda: store)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(routes.workspace_router)
    path = "/v1/workspaces/example"
    with TestClient(app) as client:
        question = client.get(path + "/questions").json()["items"][0]
        answer_path = path + f"/questions/{question['id']}/answer?revision_id=r1"
        assert client.post(answer_path, json={"skip": True}).json()["revision_id"] == "r1"
        assert client.get(path + "/questions").json()["items"][0]["id"] == question["id"]
        for invalid in ({"same": "true"}, {"same": 1}, {"same": None},
                        {"same": True, "skip": True}, {"candidate_id": "invalid"}):
            assert client.post(answer_path, json=invalid).status_code == 422
        old = store._source("example", "r1").model_dump_json(round_trip=True)
        response = client.post(answer_path, json={"same": same})
        assert response.status_code == 200
        revision_id = response.json()["revision_id"]
        assert revision_id != "r1"
        assert client.post(answer_path, json={"same": same}).status_code == 409
        rows = client.get(path + f"/revisions/{revision_id}/collections/rooms").json()
        assert len(rows) == (1 if same else 2)
        assert client.get(path + "/summary").json()["duplicates"] == 0
        assert client.get(path + "/summary").json()["unsupported_fields"] == 0
        assert store._source("example", "r1").model_dump_json(round_trip=True) == old
        restarted = RecordsRepository(store.root)
        assert not duplicates(restarted._source("example"))
        assert restarted._source("example").duplicate_decisions[0].same is same
