"""WP125 acceptance: three synthetic documents, fake HTTP, immutable publications."""

import json
import re
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from docgrain_api import records_jobs as lifecycle
from docgrain_records.discovery_models import DiscoveryDocument
from docgrain_records.review import (
    CandidateAnswer,
    answer_revision,
    auto_accepted,
    questions,
)
from docgrain_records.user_changes import (
    ManualRecord,
    ManualValue,
    NewCollection,
    NewField,
    add_collection,
    add_field,
    add_record,
    set_value,
)
from docgrain_worker import records_pipeline as pipeline
from test_u1_pipeline import WORKSPACE
from test_u1_pipeline import setup as api_setup

setup = api_setup  # Shared isolated API/job fixture.


@pytest.fixture
def company(setup):
    setup.docs.clear()
    setup.metadata_docs.clear()
    setup.versions.clear()
    setup.preparations.clear()
    for index, key in enumerate(("alpha", "beta", "gamma"), 1):
        setup.docs.append(DiscoveryDocument(source={
            "document_id": key, "workspace_id": WORKSPACE, "knowledge_revision_id": key + "-k1",
            "source_version_id": key + "-s1", "content_sha256": "a" * 64,
            "lang": "en", "filename": key + ".txt",
        }, context=f"[§1 p.1]\nItem {key}: quantity {index}.\n"))
        setup.metadata_docs.append(SimpleNamespace(id=key, workspace_id=WORKSPACE,
                                                   latest_version_id=key + "-v1"))
        setup.versions[key] = SimpleNamespace(id=key + "-v1", workspace_id=WORKSPACE,
                                              status="done", content_sha256="a" * 64)
        setup.preparations[key + "-v1"] = SimpleNamespace(status="done")
    setup.calls = []

    def fact(document, value, quote):
        return {"value": value, "lang": "en", "evidence": [{
            "document_id": document, "locator": "§1", "quote": quote}]}

    def item(doc):
        """The one synthetic line of a document: "<name>: quantity <n>."."""
        name, value = re.search(r"\n(.+?): quantity (\d+)\.", doc.context).groups()
        return name, int(value)

    def handle(request):
        payload = json.loads(request.content)
        setup.calls.append(payload)
        if payload["response_format"]["json_schema"]["name"] == "workspace_collections":
            # Use only a document actually present in this discovery call.
            present = {block["document_id"] for block in
                       json.loads(payload["messages"][1]["content"])["untrusted_source_blocks"]}
            doc = next(d for d in setup.docs if d.source.document_id in present)
            key = doc.source.document_id
            name, value = item(doc)
            labels = [{"lang": "en", "value": "Items"}, {"lang": "tr", "value": "Ürünler"}]
            response = {"collections": [{
                "key": "items", "label_i18n": labels, "description": "Synthetic inventory.",
                "fields": [{"key": field, "type": kind, "unit": None, "label_i18n": labels}
                           for field, kind in (("name", "string"), ("quantity", "integer"))],
                "examples": [{"values": [
                    {"key": "name", **fact(key, name, name)},
                    {"key": "quantity", **fact(key, value, f"quantity {value}")}]}],
            }]}
        else:
            user = json.loads(payload["messages"][1]["content"])
            key = user["document_id"]
            doc = next(d for d in setup.docs if d.source.document_id == key)
            name, value = item(doc)
            fields = {f["key"] for c in user["untrusted_collection_definitions"] for f in c["fields"]}
            response = {"records": [{"type": "items", **{
                field: [fact(key, name, name) if field == "name"
                        else fact(key, value, f"quantity {value}")]
                if field in {"name", "quantity"} else [] for field in fields}}]}
            focus = re.search(r"This pass extracts ONLY (\w+) records", payload["messages"][0]["content"])
            if focus and focus.group(1) != "items":
                response = {"records": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response)}}]})
    setup.transport = httpx.MockTransport(handle)
    return setup


def run(company, request):
    key = lifecycle.start(WORKSPACE, request)
    pipeline.process_job(key, company.transport, lambda *_args, **_kw: deepcopy(company.docs))
    job = company.memory.locate(key)
    assert job["status"] == "done", (job["error_code"], job["stage"])
    return company.store._source(WORKSPACE), job["metadata"]


def approve(company, base, fields=("name", "quantity")):
    for question in list(auto_accepted(base)):
        if question["field"] not in fields:
            continue
        base = answer_revision(base, question["id"], CandidateAnswer(
            candidate_id=question["options"][0]["candidate_id"]))
        company.store.publish(base)
    return base


def change(company, key="alpha", value=9, *, quote_stays=False, hash_changes=True):
    doc = next(d for d in company.docs if d.source.document_id == key)
    doc.context = (doc.context + "Additional text.\n" if quote_stays else
                   f"[§1 p.1]\nItem {key}: quantity {value}.\n")
    doc.source.knowledge_revision_id = key + "-k2"
    doc.source.source_version_id = key + "-s2"
    if hash_changes:
        doc.source.content_sha256 = "b" * 64
        company.versions[key].content_sha256 = "b" * 64


def add(company, key, context):
    """A new synthetic document in the workspace (its first version)."""
    company.docs.append(DiscoveryDocument(source={
        "document_id": key, "workspace_id": WORKSPACE, "knowledge_revision_id": key + "-k1",
        "source_version_id": key + "-s1", "content_sha256": "c" * 64,
        "lang": "en", "filename": key + ".txt",
    }, context=f"[§1 p.1]\n{context}\n"))
    company.metadata_docs.append(SimpleNamespace(id=key, workspace_id=WORKSPACE,
                                                 latest_version_id=key + "-v1"))
    company.versions[key] = SimpleNamespace(id=key + "-v1", workspace_id=WORKSPACE,
                                            status="done", content_sha256="c" * 64)
    company.preparations[key + "-v1"] = SimpleNamespace(status="done")


def answer_value(company, revision, question, value):
    choice = next(o["candidate_id"] for o in question["options"] if o["value"] == value)
    revision = answer_revision(revision, question["id"], CandidateAnswer(candidate_id=choice))
    company.store.publish(revision)
    return revision


def approved(company, revision):
    return json.loads(company.store.read(WORKSPACE, revision.id, "items", mode="approved"))


def test_unchanged_reuses_all_documents_and_keeps_every_human_decision(company, monkeypatch):
    first, _ = run(company, "first")
    base = approve(company, first)
    old_bytes = company.store.read(WORKSPACE, base.id, "items", mode="approved")
    calls = len(company.calls)
    monkeypatch.setattr(pipeline.Pipeline, "_structure_result", lambda *_: pytest.fail("re-extracted"))
    updated, metadata = run(company, "update")
    assert len(company.calls) == calls
    assert metadata["document_reuse"]["reused"] == 3
    assert metadata["document_reuse"]["processed"] == 0
    assert metadata["document_reuse"]["model_calls_saved"] >= 6
    assert updated.records == base.records
    assert updated.decisions == base.decisions and updated.history == base.history
    assert updated.parent_id == base.id and updated.lineage_id == base.lineage_id
    assert metadata["carry_forward"] == {
        "kept_decisions": 6, "reasked_decisions": 0, "new_values": 0, "removed_values": 0}
    assert company.store.read(WORKSPACE, base.id, "items", mode="approved") == old_bytes


def test_changed_accepted_value_asks_once_with_both_sources_and_keeps_old_publication(company):
    base = approve(company, run(company, "first")[0])
    old_bytes = company.store.read(WORKSPACE, base.id, "items", mode="approved")
    change(company)
    updated, metadata = run(company, "update")
    pending = questions(updated)
    assert len(pending) == 1
    question = pending[0]
    assert question["source_changed"] and "önceki onaylı değer 1" in question["question_tr"]
    assert "yeni değer 9" in question["question_tr"]
    assert {o["value"] for o in question["options"]} == {1, 9}
    merged = next(r for r in updated.records if r.id == question["record_id"]).fields["quantity"]
    assert merged.review_state == "needs_review"
    assert {e.source_version_id for c in merged.candidates for e in c.evidence} == {"alpha-s1", "alpha-s2"}
    assert sorted(row["quantity"] for row in approved(company, updated)) == [1, 2, 3]
    assert metadata["document_reuse"]["reused"] == 2
    assert metadata["carry_forward"]["reasked_decisions"] == 1
    for old in base.records:
        new = next(r for r in updated.records if r.id == old.id)
        assert new.fields["name"].candidates[0].review_state == "accepted"
        if old.id != question["record_id"]:
            assert new == old
    # Pending question is stable on another unchanged run; answering publishes the new value.
    again, _ = run(company, "again")
    assert questions(again) == pending
    selected = next(o["candidate_id"] for o in question["options"] if o["value"] == 9)
    answered = answer_revision(again, question["id"], CandidateAnswer(candidate_id=selected))
    company.store.publish(answered)
    assert questions(answered) == []
    assert sorted(row["quantity"] for row in approved(company, answered)) == [2, 3, 9]
    final, _ = run(company, "answered-update")
    assert questions(final) == [] and final.history == answered.history
    assert sorted(row["quantity"] for row in approved(company, final)) == [2, 3, 9]
    assert company.store.read(WORKSPACE, base.id, "items", mode="approved") == old_bytes


def test_changed_unreviewed_value_uses_decision_20(company):
    base = approve(company, run(company, "first")[0], fields=("name",))
    assert len(base.history) == 3
    change(company)
    updated, metadata = run(company, "update")
    assert questions(updated) == []
    assert sorted(row["quantity"] for row in approved(company, updated)) == [2, 3, 9]
    assert metadata["carry_forward"]["new_values"] == 1
    assert metadata["carry_forward"]["reasked_decisions"] == 0


@pytest.mark.parametrize("hash_changes", [True, False])
def test_changed_document_with_same_quote_keeps_decisions(company, hash_changes):
    base = approve(company, run(company, "first")[0])
    change(company, quote_stays=True, hash_changes=hash_changes)
    updated, metadata = run(company, "update")
    assert metadata["document_reuse"]["processed"] == 1
    assert updated.history == base.history and updated.decisions == base.decisions
    assert questions(updated) == []
    assert sorted(row["quantity"] for row in approved(company, updated)) == [1, 2, 3]


def test_user_edit_field_collection_and_record_survive(company):
    base = approve(company, run(company, "first")[0])
    record = next(r for r in base.records if r.fields["name"].accepted().value == "Item alpha")
    base = set_value(base, record.id, "quantity", ManualValue(value=17, note="Sayım"))
    company.store.publish(base)
    base = add_field(base, "items", NewField(key="note", label="Not", type="string"))
    company.store.publish(base)
    base = set_value(base, record.id, "note", ManualValue(value="Elle eklendi"))
    company.store.publish(base)
    base = add_collection(base, NewCollection(key="checks", label="Kontroller", identity="name",
        fields=[NewField(key="name", label="Ad", type="string")]))
    company.store.publish(base)
    base = add_record(base, "checks", ManualRecord(values={"name": "Özel kontrol"}))
    company.store.publish(base)
    change(company)
    updated, _ = run(company, "update")
    new_record = next(r for r in updated.records if r.id == record.id)
    assert new_record.fields["quantity"].accepted().value == 17
    assert new_record.fields["note"] == record_field(base, record.id, "note")
    assert updated.user_changes == base.user_changes
    assert next(r for r in updated.records if r.type == "checks") == base.records[-1]
    # The changed document gives another value: asked, never silently rejected (lead review).
    (question,) = questions(updated)
    assert question["record_id"] == record.id and question["field"] == "quantity"
    assert question["question_tr"] == ("Değişen belge farklı bir değer veriyor: onaylı değer 17, "
                                       "belgedeki değer 9")
    assert {o["value"] for o in question["options"]} == {17, 9}
    assert sorted(row["quantity"] for row in approved(company, updated)) == [2, 3, 17]
    again, _ = run(company, "again")
    assert questions(again) == [question]
    answered = answer_value(company, again, question, 17)
    final, metadata = run(company, "answered")
    assert questions(final) == [] and metadata["carry_forward"]["reasked_decisions"] == 0
    assert record_field(final, record.id, "quantity").accepted().value == 17
    assert final.history == answered.history


def record_field(revision, record_id, field):
    return next(r for r in revision.records if r.id == record_id).fields[field]


def test_removed_document_keeps_values_as_no_current_source_questions(company):
    base = approve(company, run(company, "first")[0])
    company.docs.pop(0)
    company.metadata_docs.pop(0)
    updated, metadata = run(company, "remove")
    assert len(updated.documents) == 2 and len(updated.records) == 3
    assert len(questions(updated)) == 2
    assert all("Güncel kaynak yok" in q["question_tr"] for q in questions(updated))
    assert sorted(row["quantity"] for row in approved(company, updated)) == [1, 2, 3]
    assert metadata["carry_forward"]["removed_values"] == 2
    assert company.store.read(WORKSPACE, base.id, "items", mode="approved")


def test_update_still_rejects_concurrent_publication(company, monkeypatch):
    base = approve(company, run(company, "first")[0])
    original = pipeline.Pipeline.merge
    def moved(self):
        original(self)
        child = base.model_copy(deep=True)
        child.id = "concurrent-publication"
        company.store.publish(child)
    monkeypatch.setattr(pipeline.Pipeline, "merge", moved)
    key = lifecycle.start(WORKSPACE, "update")
    pipeline.process_job(key, company.transport, lambda *_: deepcopy(company.docs))
    assert company.memory.locate(key)["error_code"] == "publication_changed"
    assert lifecycle.head(company.store, WORKSPACE) == "concurrent-publication"


def test_document_skipped_while_model_was_off_is_read_once_it_is_on(setup):
    from test_structure_first import run as structure_run
    from test_structure_first import use_sources

    doclings = use_sources(setup)
    setup.settings["enabled"] = False
    job, model = structure_run(setup, lifecycle.start(WORKSPACE, "model-off"), doclings)
    assert job["status"] == "done" and model.calls == []
    setup.settings["enabled"] = True
    job, model = structure_run(setup, lifecycle.start(WORKSPACE, "model-on"), doclings)
    assert job["status"] == "done", job
    assert model.calls  # only the prose document (asserted inside the fake model)
    metadata = setup.memory.locate(job["job_id"])["metadata"]
    assert metadata["document_reuse"]["reused"] == 2
    assert metadata["document_reuse"]["processed"] == 1
    assert "policies" in {r.type for r in setup.store._source(WORKSPACE).records}


def test_same_list_answer_holds_when_one_list_document_changes(setup):
    from test_structure_cross_language import en_source, source, tr_source
    from test_structure_cross_language import use_sources as cross_sources
    from test_structure_first import all_questions
    from test_structure_first import run as structure_run

    doclings = cross_sources(setup, tr_source(), en_source("Our venues", identity="Venue"))
    job, _ = structure_run(setup, lifecycle.start(WORKSPACE, "first"), doclings)
    (merge,) = [q for q in all_questions(setup) if q["kind"] == "collection_merge"]
    answer = setup.client.post(f"/v1/workspaces/{WORKSPACE}/questions/{merge['id']}/answer",
                               json={"same": True})
    assert answer.status_code == 200, answer.text
    changed, raw = source("tr", "Restoranlar", [["Restoran", "Açılış saatleri", "Mutfak"],
                                               ["Balık restoran", "19:00-23:00", "Deniz ürünleri"]], "tr")
    changed.source.knowledge_revision_id, changed.source.source_version_id = "tr-k2", "tr-s2"
    changed.source.content_sha256 = "b" * 64
    setup.versions["tr"].content_sha256 = "b" * 64
    setup.docs[:] = [changed if d.source.document_id == "tr" else d for d in setup.docs]
    doclings["tr"] = raw
    job, model = structure_run(setup, lifecycle.start(WORKSPACE, "update"), doclings)
    assert job["status"] == "done" and model.calls == []
    metadata = setup.memory.locate(job["job_id"])["metadata"]
    assert metadata["document_reuse"] == {"reused": 1, "processed": 1, "model_calls_saved": 0}
    current = setup.store._source(WORKSPACE)
    assert len(current.workspace_schema["collections"]) == 1
    assert all(q["kind"] != "collection_merge" for q in all_questions(setup))
    assert current.collection_merge_decisions[-1].same is True


def test_keeping_the_old_value_is_not_asked_again_while_documents_are_unchanged(company):
    approve(company, run(company, "first")[0])
    change(company)
    updated, _ = run(company, "update")
    (question,) = questions(updated)
    kept = next(o["candidate_id"] for o in question["options"] if o["value"] == 1)
    answered = answer_revision(updated, question["id"], CandidateAnswer(candidate_id=kept))
    company.store.publish(answered)
    final, metadata = run(company, "after-answer")
    assert questions(final) == [] and final.history == answered.history
    assert sorted(row["quantity"] for row in approved(company, final)) == [1, 2, 3]
    assert metadata["carry_forward"]["reasked_decisions"] == 0


def test_removed_document_questions_stay_until_answered_then_stay_answered(company):
    approve(company, run(company, "first")[0])
    company.docs.pop(0)
    company.metadata_docs.pop(0)
    removed, _ = run(company, "remove")
    pending = questions(removed)
    again, _ = run(company, "again")
    assert questions(again) == pending
    for question in pending:
        again = answer_revision(again, question["id"], CandidateAnswer(
            candidate_id=question["options"][0]["candidate_id"]))
        company.store.publish(again)
    final, _ = run(company, "answered")
    assert questions(final) == []
    assert sorted(row["quantity"] for row in approved(company, final)) == [1, 2, 3]


def test_update_notes_in_the_job_summary(company):
    approve(company, run(company, "first")[0])
    change(company)
    key = lifecycle.start(WORKSPACE, "update")
    pipeline.process_job(key, company.transport, lambda *_args, **_kw: deepcopy(company.docs))
    notes = company.client.get(f"/v1/workspaces/{WORKSPACE}/record-jobs/{key}").json()["summary"]["notes"]
    assert "2 belge değişmediği için yeniden okunmadı" in notes
    assert "1 onaylı değerin belgesi değişti; soru olarak soruldu" in notes


@pytest.mark.parametrize("choice", [1, 5])
def test_new_document_with_another_value_for_an_approved_field_asks_once(company, choice):
    base = approve(company, run(company, "first")[0])
    add(company, "delta", "Item alpha: quantity 5.")
    updated, metadata = run(company, "new-document")
    (question,) = questions(updated)
    assert question["field"] == "quantity" and question["source_changed"]
    assert question["question_tr"] == ("Yeni belge farklı bir değer veriyor: onaylı değer 1, "
                                       "belgedeki değer 5")
    assert {o["value"] for o in question["options"]} == {1, 5}
    assert metadata["carry_forward"]["reasked_decisions"] == 1
    assert metadata["document_reuse"]["reused"] == 3
    assert metadata["document_reuse"]["processed"] == 1
    assert sorted(row["quantity"] for row in approved(company, updated)) == [1, 2, 3]
    assert len(updated.records) == len(base.records)
    again, _ = run(company, "again")
    assert questions(again) == [question]
    answered = answer_value(company, again, question, choice)
    final, metadata = run(company, "answered")
    assert questions(final) == [] and metadata["carry_forward"]["reasked_decisions"] == 0
    assert final.history == answered.history
    assert sorted(row["quantity"] for row in approved(company, final)) == sorted([choice, 2, 3])


def test_unchanged_documents_never_reopen_an_answered_conflict(company):
    add(company, "delta", "Item alpha: quantity 5.")
    first, _ = run(company, "first")
    (conflict,) = [q for q in questions(first) if q["field"] == "quantity"]
    answered = answer_value(company, first, conflict, 5)
    final, metadata = run(company, "unchanged")
    assert [q for q in questions(final) if q["field"] == "quantity"] == []
    assert metadata["document_reuse"]["processed"] == 0
    assert final.history == answered.history


@pytest.mark.parametrize("same", [True, False])
def test_duplicate_answer_survives_an_update(company, same):
    from docgrain_records.review import DuplicateAnswer

    add(company, "delta", "Alpha item suite: quantity 1.")
    first, _ = run(company, "first")
    (duplicate,) = [q for q in questions(first) if q["kind"] == "duplicate"]
    answered = answer_revision(first, duplicate["id"], DuplicateAnswer(same=same))
    company.store.publish(answered)
    count = len(answered.records)
    assert count == (3 if same else 4)
    change(company, key="beta", value=7)
    updated, metadata = run(company, "update")
    assert metadata["document_reuse"]["processed"] == 1
    assert [q for q in questions(updated) if q["kind"] == "duplicate"] == []
    assert len(updated.records) == count
    assert updated.duplicate_decisions == answered.duplicate_decisions


def test_job_read_exposes_update_counts(company):
    approve(company, run(company, "first")[0])
    change(company)
    key = lifecycle.start(WORKSPACE, "update")
    pipeline.process_job(key, company.transport, lambda *_args, **_kw: deepcopy(company.docs))
    counts = company.client.get(f"/v1/workspaces/{WORKSPACE}/record-jobs/{key}").json()["update"]
    assert counts["reused"] == 2 and counts["processed"] == 1 and counts["model_calls_saved"] >= 4
    assert counts["reasked_decisions"] == 1 and counts["kept_decisions"] == 5
    assert counts["new_values"] == 1 and counts["removed_values"] == 1
    assert all(isinstance(value, int) for value in counts.values())
