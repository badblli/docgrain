"""WP64: alternating Saturdays, source-program swaps and precise date differences."""

import json
from datetime import date, timedelta

import pytest
import test_review_decisions as review_tests
from docgrain_records.export import export_bundle, project_records
from docgrain_records.merge_models import FactCandidate, MergeRevision
from docgrain_records.review import DocumentAnswer, answer_revision, questions, summary
from docgrain_records.schedule import infer_schedule
from test_records_export import candidate
from test_review_decisions import BASE, answer
from test_schema_driven_records import accepted

review_setup = review_tests.setup


def series(start, end="2025-09-27", interval=14):
    current, last = date.fromisoformat(start), date.fromisoformat(end)
    result = []
    while current <= last:
        result.append(current.isoformat())
        current += timedelta(days=interval)
    return result


def programs():
    a, b = series("2025-05-24"), series("2025-05-31")
    return {"A": {"doc-example": a, "doc-second": [d for d in a if d < "2025-07-01"] +
                  [d for d in b if d >= "2025-07-01"]},
            "B": {"doc-example": b, "doc-second": [d for d in b if d < "2025-07-01"] +
                  [d for d in a if d >= "2025-07-01"]}}


def schedule_revision(tmp_path, data=None, *, native=False):
    schema = accepted(tmp_path, "workspace-example", "events", "title").schema
    definition = schema["collections"][0]["fields"][1]
    definition.update(key="date", type="string_list" if native else "string")
    schema["collections"][0]["fields"] = schema["collections"][0]["fields"][:2]
    records = []
    for title, sources in (data or programs()).items():
        values = []
        if native:
            for index, (document, dates) in enumerate(sorted(sources.items())):
                item = candidate(dates, "needs_review", id=f"{title}-{index}")
                item["evidence"][0].update(document_id=document, quote=", ".join(dates))
                values.append(item)
        else:
            for index, value in enumerate(sorted(set.union(*(set(v) for v in sources.values())))):
                item = candidate(value, "needs_review", id=f"{title}-{index:02}")
                citation = item["evidence"][0]
                item["evidence"] = [{**citation, "document_id": document, "locator": "§165"}
                                    for document, dates in sorted(sources.items()) if value in dates]
                values.append(item)
        records.append({"id": title, "type": "events", "fields": {
            "title": {"primary_lang": "en", "candidates": [candidate(title, id=title + "-title")]},
            "date": {"primary_lang": "en", "candidates": values}}})
    return MergeRevision.model_validate({
        "workspace_id": "workspace-example", "id": "saturday-programs",
        "workspace_schema": schema, "records": records,
        "documents": [{"document_id": document, "document_name": name,
                       "source_version_id": "s1", "knowledge_revision_id": "k1"}
                      for document, name in [("doc-example", "Birinci program.pdf"),
                                             ("doc-second", "İkinci program.pdf")]]})


def test_inference_dates_remain_truth_and_summary_is_deterministic():
    dates = series("2025-05-24")
    expected = {"weekday": "Saturday", "every_days": 14, "from": dates[0], "to": dates[-1],
                "missing": [], "extra": [],
                "label_tr": "2 haftada bir Cumartesi, 24 May – 27 Eyl 2025"}
    assert infer_schedule(dates) == expected
    assert infer_schedule(list(reversed(dates)) + dates[:2]) == expected
    assert infer_schedule([date.fromisoformat(d).strftime("%d.%m.%Y") for d in dates]) == expected
    missing = dates[4]
    extra = "2025-07-07"
    schedule = infer_schedule([d for d in dates if d != missing] + [extra])
    assert schedule["every_days"] == 14 and schedule["weekday"] == "Saturday"
    assert schedule["missing"] == [missing] and schedule["extra"] == [extra]
    assert "eksik:" in schedule["label_tr"] and "ek:" in schedule["label_tr"]


def test_weekly_multiple_weekdays_and_cross_year_labels():
    weekly = series("2025-12-20", "2026-01-17", interval=7)
    schedule = infer_schedule(weekly)
    assert schedule["every_days"] == 7 and "20 Ara 2025 – 17 Oca 2026" in schedule["label_tr"]
    mondays = [(date.fromisoformat(d) + timedelta(days=2)).isoformat() for d in weekly]
    schedule = infer_schedule(weekly + mondays)
    assert schedule["weekday"] == ["Monday", "Saturday"]
    assert schedule["every_days"] == 7 and schedule["missing"] == schedule["extra"] == []


@pytest.mark.parametrize("values", [[], ["2025-05-24", "2025-06-07"],
                                    ["2025-05-24", "2025-06-07", "2025-02-30"],
                                    ["2025-05-24", "2025-06-05", "2025-06-28"],
                                    ["2025-07-01", "2025-07-02", "2025-07-03"]])
def test_no_inference_for_invalid_short_or_nonweekly_dates(values):
    assert infer_schedule(values) is None


@pytest.mark.parametrize("native", [False, True])
def test_exact_finding_before_after_counts_one_swap(tmp_path, native):
    revision = schedule_revision(tmp_path, native=native)
    before = revision.model_dump_json(round_trip=True)
    old_slots = [r.fields["date"].candidates for r in revision.records]
    assert len(old_slots) == 2
    if not native:
        assert [len(slot) for slot in old_slots] == [16, 16]
    question, = questions(revision)
    assert question["kind"] == "schedule_swap"
    assert question["records"] == question["record_ids"] == ["A", "B"]
    assert question["period_label_tr"] == "Temmuz'dan itibaren"
    assert question["question_tr"] == (
        "Temmuz'dan itibaren A ve B'nin cumartesileri iki belgede yer değiştirmiş; hangi belge doğru?")
    assert len(question["options"]) == 2 and question["allow_all"] is False
    assert [o["document_name"] for o in question["options"]] == [
        "Birinci program.pdf", "İkinci program.pdf"]
    assert all("2 haftada bir Cumartesi" in o["summary_tr"] for o in question["options"])
    assert summary(revision, "unused")["conflicts"] == 1
    assert summary(revision, "unused")["collections"][0]["pending_records"] == 2
    revision.records.reverse()
    for record in revision.records:
        record.fields["date"].candidates.reverse()
        for item in record.fields["date"].candidates:
            item.evidence.reverse()
    assert questions(revision) == [question]
    revision.records.reverse()
    for record in revision.records:
        record.fields["date"].candidates.reverse()
        for item in record.fields["date"].candidates:
            item.evidence.reverse()
    assert revision.model_dump_json(round_trip=True) == before


@pytest.mark.parametrize("document", ["doc-example", "doc-second"])
@pytest.mark.parametrize("native", [False, True])
def test_api_swap_answer_publishes_both_programs_with_history_and_immutable_base(
        tmp_path, review_setup, document, native):
    client, store = review_setup
    revision = schedule_revision(tmp_path, native=native)
    store.publish(revision)
    original = store.read("workspace-example", revision.id, "events")
    result = client.get(BASE + "/questions").json()
    assert result["total"] == 1
    question, = result["items"]
    response = answer(client, question, {"document_id": document})
    assert response.status_code == 200 and response.json()["remaining"] == 0
    child = response.json()["revision_id"]
    for mode in ("preview", "approved"):
        rows = client.get(BASE + f"/revisions/{child}/collections/events?mode={mode}").json()
        for row in rows:
            assert set(row["date"]) == set(programs()[row["id"]][document])
            metadata = row["_meta"]["fields"]["date"]
            assert metadata["review_state"] == "accepted"
            assert all(e["quote"] for e in metadata["evidence"])
            assert any(e["document_id"] == document for e in metadata["evidence"])
        if document == "doc-example":
            assert all(row["_meta"]["fields"]["date"]["schedule"]["every_days"] == 14 for row in rows)
    source = store._source("workspace-example")
    assert source.parent_id == source.lineage_id == revision.id
    assert [(h.question_id, h.record_id) for h in source.history] == [(question["id"], "A"),
                                                                    (question["id"], "B")]
    assert all(h.candidate_ids and not h.all for h in source.history)
    assert client.get(BASE + "/summary").json()["conflicts"] == 0
    assert store.read("workspace-example", revision.id, "events") == original
    assert answer(client, question, {"document_id": document}).status_code == 409


@pytest.mark.parametrize("native", [False, True])
def test_agreeing_partial_programs_union_evidence_without_approval(tmp_path, native):
    dates = series("2025-05-24")
    revision = schedule_revision(tmp_path, {"A": {"doc-example": dates[:7],
                                                 "doc-second": dates[3:]}}, native=native)
    assert questions(revision) == []
    row, = project_records(revision)["events"]
    assert set(row["date"]) == set(dates)
    meta = row["_meta"]["fields"]["date"]
    assert meta["schedule"]["every_days"] == 14
    assert {e["document_id"] for e in meta["evidence"]} == {"doc-example", "doc-second"}
    assert meta["review_state"] == "proposed" and row["_meta"]["conflicts"] == []
    assert "date" not in project_records(revision, mode="approved")["events"][0]
    assert meta["schedule"]["label_tr"] in export_bundle(revision)["events.context.md"].decode()


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("extra", ["2025-07-07", "2025-07-12", "2025-07-05"])
def test_one_extra_or_missing_date_asks_only_the_difference(tmp_path, native, extra):
    dates = series("2025-05-24")
    first = [d for d in dates if d != extra]
    second = sorted(set(dates) | {extra})
    revision = schedule_revision(tmp_path, {"A": {"doc-example": first,
                                                 "doc-second": second}}, native=native)
    question, = questions(revision)
    assert question["kind"] == "schedule_conflict" and question["differing_dates"] == [extra]
    assert [o["value"] for o in question["options"]] == [[], [extra]]
    assert "Bu tarihlerde etkinlik yok" == question["options"][0]["summary_tr"]
    assert "2025" in question["options"][1]["summary_tr"]
    assert all("2025-05-24" not in o["display"] for o in question["options"])
    updated = answer_revision(revision, question["id"], DocumentAnswer(document_id="doc-second"))
    assert questions(updated) == []
    assert set(project_records(updated, mode="approved")["events"][0]["date"]) == set(second)


@pytest.mark.parametrize("body", [{"document_id": "foreign"}, {"all": True},
                                  {"candidate_id": "A-00"}, {"value": "2025-07-05", "note": ""}])
def test_swap_rejects_nonprogram_answers_atomically(tmp_path, review_setup, body):
    client, store = review_setup
    revision = schedule_revision(tmp_path)
    store.publish(revision)
    question, = client.get(BASE + "/questions").json()["items"]
    original = store.read("workspace-example", revision.id, "events")
    assert answer(client, question, body).status_code == 422
    assert store.list_revisions("workspace-example")[0] == revision.id
    assert store.read("workspace-example", revision.id, "events") == original


def test_partial_cross_match_and_third_source_never_hide_conflicts(tmp_path):
    data = programs()
    data["B"]["doc-second"].remove("2025-07-05")
    revision = schedule_revision(tmp_path, data)
    assert [q["kind"] for q in questions(revision)] == ["schedule_conflict", "schedule_conflict"]
    data = programs()
    data["A"]["doc-third"] = series("2025-05-24")
    revision = schedule_revision(tmp_path / "third", data)
    revision.documents.append(revision.documents[0].model_copy(update={"document_id": "doc-third"}))
    assert len(questions(revision)) == 2 and all(q["kind"] != "schedule_swap" for q in questions(revision))


def test_answer_is_language_scoped_and_retains_preexisting_rejections(tmp_path):
    revision = schedule_revision(tmp_path)
    field = revision.records[1].fields["date"]
    field.candidates.extend([FactCandidate.model_validate(candidate("2025-07-04", "rejected", id="old")),
                             FactCandidate.model_validate(candidate("2025-07-06", "needs_review",
                                                                    lang="tr", id="translated"))])
    question = next(q for q in questions(revision) if q["kind"] == "schedule_swap")
    updated = answer_revision(revision, question["id"], DocumentAnswer(document_id="doc-example"))
    field = updated.records[1].fields["date"]
    assert [c.review_state for c in field.candidates[-2:]] == ["rejected", "needs_review"]
    assert field.multi_value_languages == ["en"]
    assert field.accepted("tr") is None
    assert json.loads(export_bundle(updated, "approved")["events.json"])[1]["date"]
