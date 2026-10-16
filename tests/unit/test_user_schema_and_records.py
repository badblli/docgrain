"""User additions keep old publications and evidence while respecting job fencing."""

import json

import pytest
from docgrain_api.records_repository import QuestionStale, RecordsRepository
from docgrain_api.routers import records as routes
from docgrain_records.discovery_models import DiscoveryDocument
from docgrain_records.export import export_bundle
from docgrain_records.merge_models import MergeRevision
from docgrain_records.targeted_fill import fill_field
from docgrain_records.user_changes import (
    ManualRecord,
    ManualValue,
    NewCollection,
    NewField,
    add_field,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_schema_driven_records import accepted


def revision(tmp_path):
    runtime = accepted(tmp_path)
    return MergeRevision.model_validate({
        "workspace_id": "clinic", "id": "r1", "workspace_schema": runtime.schema,
        "documents": [{"document_id": "clinic-doc", "source_version_id": "clinic-doc-v1",
                       "knowledge_revision_id": "clinic-doc-k1"}],
        "records": [{"id": "rec-a", "type": "services", "fields": {"name": {
            "primary_lang": "en", "candidates": [{"id": "fact-name", "value": "Consultation",
                "lang": "en", "review_state": "accepted", "evidence": [{
                    "document_id": "clinic-doc", "source_version_id": "clinic-doc-v1",
                    "knowledge_revision_id": "clinic-doc-k1", "locator": "§1", "quote": "Consultation"}]}]}}}],
    })


def test_schema_versions_manual_records_and_approved_evidence(tmp_path):
    base = revision(tmp_path)
    store = RecordsRepository(tmp_path / "publications")
    store.publish(base)
    field = NewField(key="duration", label="Süre", type="string")
    next_id = store.user_change("clinic", "r1", "add_field", "services", field)["revision_id"]
    field_revision = store._source("clinic", next_id)
    assert field_revision.workspace_schema["version"] == base.workspace_schema["version"] + 1
    assert len(field_revision.records) == 1 and field_revision.records[0].fields["name"] == base.records[0].fields["name"]
    assert "duration" not in field_revision.records[0].fields
    assert field_revision.user_changes[-1].who == "local"
    assert store.read("clinic", "r1", "services", mode="approved") == export_bundle(base, "approved")["services.json"]

    result = store.user_change("clinic", next_id, "set_value", "rec-a", "duration",
                               ManualValue(value="30 dakika", note="Telefonda teyit", who="staff"))
    row = json.loads(store.read("clinic", result["revision_id"], "services", mode="approved"))[0]
    assert row["duration"] == "30 dakika"
    assert row["_meta"]["fields"]["duration"]["evidence"][0]["kind"] == "user_edit"
    assert row["_meta"]["fields"]["duration"]["evidence"][0]["who"] == "staff"
    assert "30 dakika" in store.read("clinic", result["revision_id"], "services", compact=True,
                                      mode="approved").decode()

    created = store.user_change("clinic", result["revision_id"], "add_record", "services",
                                ManualRecord(values={"name": "New service", "duration": "45 dakika"},
                                             who="staff"))
    rows = json.loads(store.read("clinic", created["revision_id"], "services", mode="approved"))
    assert len(rows) == 2
    assert next(row for row in rows if row["id"] == created["record_id"])["_meta"]["fields"]["name"]["evidence"][0]["kind"] == "user_edit"
    assert len(store.list_revisions("clinic")) == 4


def test_new_collection_and_running_job_fence(tmp_path):
    base = revision(tmp_path)
    busy = False

    def fence(_workspace):
        if busy:
            raise QuestionStale("Bilgiler hazırlanıyor; işlem bitince cevaplayın.")

    store = RecordsRepository(tmp_path / "publications", before_answer=fence)
    store.publish(base)
    collection = NewCollection(key="teams", label="Ekipler", identity="name",
                               fields=[NewField(key="name", label="Ad", type="string")])
    busy = True
    with pytest.raises(QuestionStale, match="hazırlanıyor"):
        store.user_change("clinic", "r1", "add_collection", collection)
    assert store.list_revisions("clinic") == ["r1"]
    busy = False
    result = store.user_change("clinic", "r1", "add_collection", collection)
    assert result["workspace_schema_version"] == 2
    assert json.loads(store.read("clinic", result["revision_id"], "teams")) == []


def test_schema_edit_api_returns_clear_conflict(tmp_path, monkeypatch):
    def busy(_workspace):
        raise QuestionStale("Bilgiler hazırlanıyor; işlem bitince cevaplayın.")

    store = RecordsRepository(tmp_path / "publications", before_answer=busy)
    store.publish(revision(tmp_path))
    monkeypatch.setattr(routes, "repository", lambda: store)
    app = FastAPI()
    app.include_router(routes.workspace_router)
    with TestClient(app) as client:
        response = client.post("/v1/workspaces/clinic/collections/services/fields?revision_id=r1",
                               json={"key": "duration", "label": "Süre", "type": "string"})
    assert response.status_code == 409
    assert "hazırlanıyor" in response.json()["detail"]


@pytest.mark.parametrize("valid", [True, False])
def test_targeted_fill_verifies_quotes_and_publishes_only_supported_values(tmp_path, valid):
    base = add_field(revision(tmp_path), "services",
                     NewField(key="duration", label="Süre", type="string"))
    context = "[§1 p.1]\nConsultation Duration: 30 minutes\n"
    document = DiscoveryDocument(source={
        "workspace_id": "clinic", "document_id": "clinic-doc",
        "source_version_id": "clinic-doc-v1", "knowledge_revision_id": "clinic-doc-k1",
        "content_sha256": "a" * 64, "lang": "en",
    }, context=context)

    class FakeChat:
        def complete(self, _messages, **_kwargs):
            quote = "Duration: 30 minutes" if valid else "invented quote"
            return json.dumps({"records": [{"type": "services", "name": [{
                "value": "Consultation", "lang": "en", "evidence": [{
                    "document_id": "clinic-doc", "locator": "§1", "quote": "Consultation"}]}],
                "duration": [{"value": "30 minutes", "lang": "en", "evidence": [{
                    "document_id": "clinic-doc", "locator": "§1", "quote": quote}]}]}]})

    filled, rejected = fill_field(base, "services", "duration", [document], FakeChat())
    row = json.loads(export_bundle(filled, "approved")["services.json"])[0]
    if valid:
        assert row["duration"] == "30 minutes" and not rejected
        assert row["_meta"]["fields"]["duration"]["evidence"][0]["quote"] == "Duration: 30 minutes"
    else:
        assert "duration" not in row and rejected


def test_failed_fill_still_adds_the_field_with_a_note(tmp_path):
    def broken(_store, revision, _collection, _field):
        revision.records[0].fields["duration"] = revision.records[0].fields["name"]
        raise RuntimeError("model unreachable")

    store = RecordsRepository(tmp_path / "publications", field_filler=broken)
    store.publish(revision(tmp_path))
    result = store.user_change("clinic", "r1", "add_field", "services",
                               NewField(key="duration", label="Süre", type="string"))
    added = store._source("clinic", result["revision_id"])
    assert "duration" not in added.records[0].fields
    assert added.workspace_schema["version"] == 2
    assert "elle" in result["note"] and added.user_changes[-1].note == result["note"]


def test_manual_value_replaces_only_the_shown_language(tmp_path):
    base = revision(tmp_path)
    base.records[0].fields["name"].candidates.append(
        base.records[0].fields["name"].candidates[0].model_copy(
            update={"id": "fact-name-tr", "value": "Muayene", "lang": "tr"}))
    store = RecordsRepository(tmp_path / "publications")
    store.publish(base)
    result = store.user_change("clinic", "r1", "set_value", "rec-a", "name",
                               ManualValue(value="First consultation", note="Fiyat listesi eski"))
    name = store._source("clinic", result["revision_id"]).records[0].fields["name"]
    assert name.accepted("en").value == "First consultation"
    assert name.accepted("tr").value == "Muayene"
