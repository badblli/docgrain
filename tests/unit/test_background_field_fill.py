"""WP120 acceptance: field publication is immediate; only a fenced worker calls chat."""

import json
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import httpx
import pytest
import test_u1_pipeline as u1
from docgrain_api import records_jobs as lifecycle
from docgrain_records.discovery_models import WorkspaceSchema
from docgrain_records.discovery_store import source_directory
from docgrain_worker import records_pipeline as pipeline
from test_u1_pipeline import BASE, SECRET, WORKSPACE, fact, run, start

setup = u1.setup


def prepare(env):
    key = start(env)
    result = run(env, key)
    assert result["status"] == "done"
    return key, result["revision_id"]


def add(env, revision, field="details"):
    return env.client.post(BASE + "/collections/rooms/fields?revision_id=" + revision,
                           json={"key": field, "label": "Açıklama", "type": "string"})


class FillModel:
    def __init__(self, env, *, invalid=False, fail=False, after=None, conflict=False):
        self.env, self.invalid, self.fail, self.after = env, invalid, fail, after
        self.conflict = conflict
        self.calls = []

    def handle(self, request):
        payload = json.loads(request.content)
        self.calls.append(payload)
        # A model call must not hold the common OS lock, including on Windows.
        with self.env.store._workspace_lock(WORKSPACE):
            pass
        if self.after:
            self.after()
        if self.fail:
            raise RuntimeError(SECRET)
        document = json.loads(payload["messages"][1]["content"])["document_id"]
        fields = json.loads(payload["messages"][1]["content"])["untrusted_collection_definitions"][0]["fields"]
        field = next(item["key"] for item in fields if item["key"] != "name")
        value = ("32 m2" if document == "rooms" else "36 m2") if self.conflict else "capacity 2"
        quote = "absent quote" if self.invalid else value
        response = {"records": [{"type": "rooms", "name": [fact(document, "Garden Room")],
                                  field: [fact(document, value, quote)]}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response)}}]})


def run_fill(env, key, **kwargs):
    model = FillModel(env, **kwargs)
    pipeline.process_job(key, httpx.MockTransport(model.handle))
    return env.client.get(BASE + "/record-jobs/" + key).json(), model


def test_add_field_returns_schema_without_model_calls_and_fences_all_writes(setup, monkeypatch):
    full, base = prepare(setup)
    calls = len(setup.model.calls)
    # The superseded filler must never be used in the HTTP request.
    from docgrain_api import field_fill

    monkeypatch.setattr(field_fill, "fill_new_field", lambda *_: pytest.fail("request called filler"))
    monkeypatch.setattr(field_fill, "ChatClient", lambda *_a, **_k: pytest.fail("request created chat"))
    monkeypatch.setattr(field_fill, "load_pinned_contexts", lambda *_: pytest.fail("request read contexts"))
    response = add(setup, base)
    assert response.status_code == 200
    result = response.json()
    assert result["workspace_schema_version"] == 2 and result["fill_job_id"]
    assert len(setup.model.calls) == calls
    job = setup.memory.get(WORKSPACE, result["fill_job_id"])
    assert job["kind"] == "field_fill" and job["context_job_id"] == full
    assert job["base_revision_id"] == job["publication_head"] == result["revision_id"]
    assert job["model_enabled"] is True and job["settings_version"] == 1 and job["sources"] == []
    assert setup.dispatched[-1] == (lifecycle.QUEUE_NAME, job["job_id"])
    assert setup.store._source(WORKSPACE).user_changes[-1].note == lifecycle.FILL_QUEUED
    assert setup.store._source(WORKSPACE).user_changes[-1].fill_job_id == job["job_id"]
    schema = setup.client.get(BASE + "/collection-schema").json()
    assert schema["field_notes"]["rooms.details"] == lifecycle.FILL_QUEUED
    edit = setup.client.put(BASE + "/records/irrelevant/fields/details?revision_id=" + result["revision_id"],
                            json={"value": "manual"})
    answer = setup.client.post(BASE + "/questions/irrelevant/answer", json={"skip": True})
    restart = setup.client.post(BASE + "/record-jobs", json={"request_id": "while-fill"})
    repeated = setup.client.post(BASE + "/record-jobs", json={"request_id": "request-1"})
    assert edit.status_code == answer.status_code == restart.status_code == 409
    assert repeated.status_code == 409
    assert edit.json()["detail"] == "Yeni alan dolduruluyor; bitince tekrar deneyin."
    latest = setup.client.get(BASE + "/record-jobs/latest").json()
    assert (latest["kind"], latest["collection"], latest["field"]) == ("field_fill", "rooms", "details")


@pytest.mark.parametrize("invalid", [False, True])
def test_worker_publishes_child_with_review_rules_rejections_and_two_stages(setup, invalid):
    _, base = prepare(setup)
    added = add(setup, base).json()
    field_revision = setup.store._source(WORKSPACE)
    original_name = deepcopy(field_revision.records[0].fields["name"])
    setup.memory.stages.clear()
    job, model = run_fill(setup, added["fill_job_id"], invalid=invalid)
    assert model.calls and job["status"] == "done"
    assert setup.memory.stages == ["fill", "publish"]
    assert job["completed_stages"] == job["total_stages"] == 2
    assert all(stage["status"] == "done" for stage in job["stages"].values())
    child = setup.store._source(WORKSPACE)
    assert child.id == job["revision_id"] and child.parent_id == added["revision_id"]
    assert child.workspace_schema == field_revision.workspace_schema
    assert child.records[0].fields["name"] == original_name
    assert job["speed"]["stages"]["fill"]["calls"] == len(model.calls)
    row = json.loads(setup.store.read(WORKSPACE, child.id, "rooms", mode="approved"))[0]
    if invalid:
        assert "details" not in row and job["summary"]["rejected_fields"] == 2
        assert child.user_changes[-1].note == "Doğrulanamayan belge önerileri eklenmedi."
    else:
        assert row["details"] == "capacity 2" and job["summary"]["rejected_fields"] == 0
        assert any(d.field == "details" and d.reviewer.startswith("rule:verified") for d in child.decisions)
        assert child.user_changes[-1].note == "Belgelerde doğrulanabilen değerler eklendi; diğerleri boş kaldı."
    schema = setup.client.get(BASE + "/collection-schema").json()
    assert schema["field_notes"]["rooms.details"] == child.user_changes[-1].note


@pytest.mark.parametrize("failure,code", [("chat", "step_failed"), ("hash", "step_failed"),
                                         ("head", "publication_changed"), ("off", "guard"),
                                         ("settings", "guard")])
def test_fill_failure_preserves_empty_schema_revision_and_fixed_error(setup, failure, code):
    full, base = prepare(setup)
    added = add(setup, base).json()
    original_head = setup.store._source(WORKSPACE)
    expected_head = original_head.id
    if failure == "hash":
        schema = WorkspaceSchema.model_validate(original_head.workspace_schema)
        root = setup.store._path(WORKSPACE) / "runtime" / sha256(full.encode()).hexdigest() / "schema"
        (source_directory(root, schema.sources[0]) / "context.md").write_text("changed", encoding="utf-8")
    elif failure == "off":
        setup.settings["enabled"] = False
    elif failure == "settings":
        setup.settings["settings_version"] += 1
    elif failure == "head":
        # Simulate an offline publisher bypassing API fencing before the fill's commit.
        other = original_head.model_copy(deep=True)
        other.id = "offline-head"
        other.parent_id = original_head.id
        setup.store.publish(other)
        expected_head = other.id
    job, _ = run_fill(setup, added["fill_job_id"], fail=failure == "chat")
    assert job["status"] == "failed" and job["error_code"] == code
    assert setup.store.list_revisions(WORKSPACE)[0] == expected_head
    source = setup.store._source(WORKSPACE, added["revision_id"])
    assert source.user_changes[-1].note == lifecycle.FILL_QUEUED
    assert source.user_changes[-1].fill_job_id == added["fill_job_id"]
    assert "details" not in source.records[0].fields
    assert any(f["key"] == "details" for f in source.workspace_schema["collections"][0]["fields"])
    assert SECRET not in json.dumps(setup.memory.rows)
    assert len(setup.store.list_revisions(WORKSPACE)) == (3 if failure == "head" else 2)
    schema = setup.client.get(BASE + "/collection-schema").json()
    assert schema["field_notes"]["rooms.details"] == lifecycle.FILL_FALLBACK
    current = setup.store._source(WORKSPACE)
    later = setup.client.put(BASE + f"/records/{current.records[0].id}/fields/details?revision_id={current.id}",
                             json={"value": "Manual value"})
    assert later.status_code == 200
    child = setup.store._source(WORKSPACE)
    assert child.parent_id == current.id and child.user_changes[-2].note == lifecycle.FILL_QUEUED
    assert setup.client.get(BASE + "/collection-schema").json()["field_notes"]["rooms.details"] == lifecycle.FILL_FALLBACK


def test_model_off_adds_field_without_job_and_persists_note(setup):
    _, base = prepare(setup)
    setup.settings["enabled"] = False
    before = len(setup.memory.rows), len(setup.dispatched), len(setup.model.calls)
    result = add(setup, base).json()
    assert result["workspace_schema_version"] == 2 and "fill_job_id" not in result
    assert result["note"] == lifecycle.FILL_MODEL_OFF
    assert setup.store._source(WORKSPACE).user_changes[-1].note == result["note"]
    assert before == (len(setup.memory.rows), len(setup.dispatched), len(setup.model.calls))


@pytest.mark.parametrize("failure", ["queue", "settings", "contexts"])
def test_start_failure_still_returns_field_and_durable_fallback_note(setup, monkeypatch, failure):
    _, base = prepare(setup)
    if failure == "queue":
        def broken(*_):
            raise RuntimeError(SECRET)
        monkeypatch.setattr(lifecycle, "queue_client", lambda: SimpleNamespace(lpush=broken))
    elif failure == "settings":
        monkeypatch.delenv("U1_TEST_KEY")
    else:
        monkeypatch.setattr(lifecycle, "context_job", lambda *_: None)
    response = add(setup, base)
    assert response.status_code == 200
    result = response.json()
    assert result["workspace_schema_version"] == 2 and "fill_job_id" not in result
    assert result["note"] == lifecycle.FILL_FALLBACK
    change = setup.store._source(WORKSPACE).user_changes[-1]
    assert change.note == (lifecycle.FILL_QUEUED if failure == "queue" else lifecycle.FILL_FALLBACK)
    assert bool(change.fill_job_id) == (failure == "queue")
    assert setup.client.get(BASE + "/collection-schema").json()["field_notes"]["rooms.details"] == lifecycle.FILL_FALLBACK
    if failure == "queue":
        job = setup.memory.latest(WORKSPACE)
        assert job["status"] == "failed" and job["error_code"] == "dispatch"
    assert SECRET not in json.dumps(setup.memory.rows)


def test_second_field_skips_fill_job_context_directory(setup):
    full, base = prepare(setup)
    first = add(setup, base).json()
    done, _ = run_fill(setup, first["fill_job_id"])
    assert done["status"] == "done"
    second = add(setup, done["revision_id"], "description").json()
    assert second["workspace_schema_version"] == 3
    job = setup.memory.get(WORKSPACE, second["fill_job_id"])
    assert job["context_job_id"] == full
    done, _ = run_fill(setup, second["fill_job_id"])
    assert done["status"] == "done"


def test_fill_keeps_person_acceptances_and_makes_conflicting_values_questions(setup):
    _, base = prepare(setup)
    record = setup.store._source(WORKSPACE).records[0]
    edited = setup.client.put(BASE + f"/records/{record.id}/fields/name?revision_id={base}",
                              json={"value": "Garden Room", "note": "Person verified"})
    assert edited.status_code == 200
    before = setup.store._source(WORKSPACE).records[0].fields["name"]
    added = add(setup, edited.json()["revision_id"]).json()
    done, _ = run_fill(setup, added["fill_job_id"], conflict=True)
    assert done["status"] == "done"
    child = setup.store._source(WORKSPACE)
    assert child.records[0].fields["name"] == before
    field = child.records[0].fields["details"]
    assert {c.review_state for c in field.candidates} == {"needs_review"}
    questions = setup.client.get(BASE + "/questions").json()["items"]
    assert any(q["field"] == "details" for q in questions)


def test_settings_change_during_chat_stops_before_publication(setup):
    _, base = prepare(setup)
    added = add(setup, base).json()
    def switch_off():
        setup.settings["enabled"] = False
        setup.settings["settings_version"] += 1
    done, model = run_fill(setup, added["fill_job_id"], after=switch_off)
    assert done["status"] == "failed" and done["error_code"] == "guard"
    assert len(model.calls) == 1
    assert lifecycle.head(setup.store, WORKSPACE) == added["revision_id"]
