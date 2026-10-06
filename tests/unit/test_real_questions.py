"""WP61: repeatable facts are lists; ambiguous facts remain evidenced questions."""

import json

import pytest
import test_review_decisions as review_tests
from docgrain_api.records_repository import RecordsRepository
from docgrain_records.export import export_bundle, load_revision, project_records
from docgrain_records.match_merge import load_merge_documents, write_json
from docgrain_records.merge import JsonMergeStore
from docgrain_records.merge_models import FactCandidate, MergeRevision
from docgrain_records.review import AllAnswer, answer_revision, questions, summary
from test_records_export import candidate, fixture_revision
from test_review_decisions import BASE, answer
from test_schema_driven_records import accepted, bundle

review_setup = review_tests.setup


def repeated(tmp_path, values, field="date", field_type="string", two_documents=False):
    schema = accepted(tmp_path, "workspace-example", "events", "title").schema
    definition = schema["collections"][0]["fields"][1]
    definition.update(key=field, type=field_type)
    schema["collections"][0]["fields"] = schema["collections"][0]["fields"][:2]
    candidates = []
    for index, value in enumerate(values, 1):
        item = candidate(value, "needs_review", id=f"value-{index:02}")
        item["evidence"][0]["locator"] = f"§{index} p.{index}"
        if two_documents and index == len(values):
            item["evidence"][0]["document_id"] = "doc-second"
        candidates.append(item)
    pins = [{"document_id": document, "document_name": filename,
             "source_version_id": "s1", "knowledge_revision_id": "k1"}
            for document, filename in [("doc-example", "Etkinlik takvimi.pdf"),
                                       ("doc-second", "Yeni takvim.pdf")]]
    return MergeRevision.model_validate({
        "workspace_id": "workspace-example", "id": "recurring",
        "workspace_schema": schema, "documents": pins if two_documents else pins[:1],
        "records": [{"id": "event", "type": "events", "fields": {
            "title": {"primary_lang": "en", "candidates": [candidate("Evening show")]},
            field: {"primary_lang": "en", "candidates": candidates},
        }}],
    })


def test_nine_recurring_dates_before_after_counts_and_published_lists(tmp_path):
    values = [f"2026-07-{day:02}" for day in range(1, 10)]
    revision = repeated(tmp_path, values)
    before = revision.model_dump_json(round_trip=True)
    # WP59 treats each unresolved slot with >1 candidates as one conflict question.
    old_conflicts = sum(len([c for c in f.candidates if c.lang == "en"
                            and c.review_state != "rejected"]) > 1
                        for r in revision.records for f in r.fields.values())
    assert old_conflicts == 1
    store = RecordsRepository(tmp_path / "packs")
    store.publish(revision)
    assert store.list_questions("workspace-example") == {"total": 0, "items": []}
    result = store.workspace_summary("workspace-example")
    assert result["conflicts"] == result["needs_review"] == result["unsupported_fields"] == 0
    assert result["accepted_ratio"] == 0.5  # Inference grants no approval.
    row = json.loads(store.read("workspace-example", "recurring", "events"))[0]
    assert row["date"] == values and row["_meta"]["conflicts"] == []
    assert row["_meta"]["fields"]["date"]["review_state"] == "proposed"
    assert len(row["_meta"]["fields"]["date"]["evidence"]) == 9
    approved = json.loads(store.read("workspace-example", "recurring", "events", mode="approved"))[0]
    assert "date" not in approved
    revision.records[0].fields["date"].candidates.reverse()
    assert export_bundle(revision)["events.json"] == store.read("workspace-example", "recurring", "events")
    revision.records[0].fields["date"].candidates.reverse()
    assert revision.model_dump_json(round_trip=True) == before


def test_same_dates_from_two_documents_remain_a_question_with_file_names(tmp_path):
    revision = repeated(tmp_path, ["2026-07-01", "2026-07-02"], two_documents=True)
    question, = questions(revision)
    assert question["kind"] == "conflict" and question["allow_all"] is True
    assert [o["document_name"] for o in question["options"]] == [
        "Etkinlik takvimi.pdf", "Yeni takvim.pdf"]
    assert [o["locator"] for o in question["options"]] == ["s. 1", "s. 2"]
    assert summary(revision, "unused")["conflicts"] == 1
    assert len(project_records(revision)["events"][0]["_meta"]["conflicts"]) == 1


def test_nine_dates_with_one_section_locator_and_distinct_verified_quotes(tmp_path):
    values = [f"{day:02}.07.2026" for day in range(1, 10)]
    revision = repeated(tmp_path, values)
    candidates = revision.records[0].fields["date"].candidates
    for item in candidates:
        item.evidence[0].locator = "§165"
    assert {(e.document_id, e.source_version_id, e.knowledge_revision_id, e.locator)
            for c in candidates for e in c.evidence} == {("doc-example", "s1", "k1", "§165")}
    assert [c.evidence[0].quote for c in candidates] == values
    assert questions(revision) == []
    assert summary(revision, "unused")["conflicts"] == 0
    row = project_records(revision)["events"][0]
    assert row["date"] == values
    assert len(row["_meta"]["fields"]["date"]["evidence"]) == 9
    assert row["_meta"]["conflicts"] == []


def test_times_with_one_section_locator_and_distinct_verified_quotes(tmp_path):
    revision = repeated(tmp_path, ["16:00", "10:30"], field="time")
    candidates = revision.records[0].fields["time"].candidates
    for item in candidates:
        item.evidence[0].locator = "§165"
    assert [c.evidence[0].quote for c in candidates] == ["16:00", "10:30"]
    assert questions(revision) == []
    assert project_records(revision)["events"][0]["time"] == ["16:00", "10:30"]


def test_same_locator_dates_from_two_documents_remain_question(tmp_path):
    revision = repeated(tmp_path, ["01.07.2026", "02.07.2026"], two_documents=True)
    for item in revision.records[0].fields["date"].candidates:
        item.evidence[0].locator = "§165"
    question, = questions(revision)
    assert question["kind"] == "conflict" and len(question["options"]) == 2
    assert summary(revision, "unused")["conflicts"] == 1


@pytest.mark.parametrize("field,values", [
    ("date", ["01.07.2026", "02.07.2026"]),
    ("time", ["09:00", "17:30"]),
    ("hours", ["09:00–12:00", "14:00-17:00"]),
    ("price", ["Adult: 20 EUR", "Child: 10 EUR"]),
])
def test_repeatable_scalar_values_at_distinct_source_locations(tmp_path, field, values):
    revision = repeated(tmp_path, values, field=field)
    assert questions(revision) == []
    assert project_records(revision)["events"][0][field] == values


@pytest.mark.parametrize("field,values", [
    ("date", ["2026-02-30", "2026-07-02"]),
    ("time", ["25:00", "09:00"]),
    ("price", ["20 EUR", "10 EUR"]),
    ("price", ["Adult: 20 EUR", "Adult: 10 EUR"]),
    ("description", ["First description", "Second description"]),
])
def test_ambiguous_same_document_values_remain_questions(tmp_path, field, values):
    revision = repeated(tmp_path, values, field=field)
    assert questions(revision)[0]["kind"] == "conflict"


@pytest.mark.parametrize("quotes,expected", [
    (["Adult: 20 EUR", "Child: 10 EUR"], True),
    (["Adult: 20 EUR", "Adult: 10 EUR"], False),
    (["Adult: 25 EUR", "Child: 10 EUR"], False),
    (["20 EUR", "10 EUR"], False),
])
def test_numeric_prices_require_evidenced_distinct_variants(tmp_path, quotes, expected):
    revision = repeated(tmp_path, [20, 10], field="price", field_type="number")
    for item, quote in zip(revision.records[0].fields["price"].candidates, quotes, strict=True):
        item.evidence[0].quote = quote
    assert (questions(revision) == []) is expected
    if expected:
        assert project_records(revision)["events"][0]["price"] == [20, 10]


@pytest.mark.parametrize("change", ["shared_quote", "version", "user_edit"])
def test_automatic_lists_require_distinct_quotes_or_one_pinned_source(tmp_path, change):
    revision = repeated(tmp_path, ["2026-07-01", "2026-07-02"])
    values = revision.records[0].fields["date"].candidates
    if change == "shared_quote":
        values[1].evidence[0].locator = values[0].evidence[0].locator
        values[1].evidence[0].quote = values[0].evidence[0].quote
    elif change == "version":
        values[1].evidence[0].source_version_id = "s2"
    else:
        values[1] = FactCandidate.model_validate({
            **values[1].model_dump(), "evidence": [{"kind": "user_edit", "at": "now", "note": ""}],
        })
    assert len(questions(revision)) == 1


def test_declared_lists_union_values_and_evidence_even_across_documents(tmp_path):
    revision = repeated(tmp_path, [["music", "dance"], ["dance", "sport"]],
                        field="tags", field_type="string_list", two_documents=True)
    assert questions(revision) == []
    row = project_records(revision)["events"][0]
    assert row["tags"] == ["music", "dance", "sport"]
    assert len(row["_meta"]["fields"]["tags"]["evidence"]) == 2
    assert row["_meta"]["conflicts"] == []


def test_rejected_candidates_do_not_turn_repetition_into_a_conflict(tmp_path):
    revision = repeated(tmp_path, ["2026-07-01", "2026-07-02", "2026-07-03"], two_documents=True)
    revision.records[0].fields["date"].candidates[-1].review_state = "rejected"
    assert questions(revision) == []
    assert project_records(revision)["events"][0]["date"] == ["2026-07-01", "2026-07-02"]


def test_all_answer_publishes_list_keeps_rejections_languages_and_immutable_bytes(review_setup):
    client, store = review_setup
    revision = fixture_revision("with-rejections")
    values = revision.records[0].fields["view"].candidates
    values.extend([
        FactCandidate.model_validate(candidate("Old", "rejected", id="view-old")),
        FactCandidate.model_validate(candidate("Bahçe", "needs_review", lang="tr", id="view-tr")),
    ])
    store.publish(revision)
    original = store.read("workspace-example", revision.id, "rooms")
    conflict = client.get(BASE + "/questions").json()["items"][0]
    assert conflict["allow_all"] is True
    response = answer(client, conflict, {"all": True})
    assert response.status_code == 200 and response.json()["remaining"] == 2
    child_id = response.json()["revision_id"]
    source = RecordsRepository(store.root)._source("workspace-example")
    field = source.records[0].fields["view"]
    assert [c.review_state for c in field.candidates] == [
        "accepted", "accepted", "rejected", "needs_review"]
    assert field.multi_value_languages == ["en"]
    assert field.primary.value == field.accepted().value == ["Garden", "Sea"]
    assert source.parent_id == revision.id and source.history[0].all is True
    assert source.history[0].candidate_ids == ["view-a", "view-b"]
    for mode in ("preview", "approved"):
        rows = client.get(BASE + f"/revisions/{child_id}/collections/rooms?mode={mode}").json()
        row = next(r for r in rows if r["id"] == "rec-room")
        assert row["view"] == ["Garden", "Sea"]
        assert len(row["_meta"]["fields"]["view"]["evidence"]) == 2
    assert store.read("workspace-example", revision.id, "rooms") == original
    assert "view" not in json.loads(store.read(
        "workspace-example", revision.id, "rooms", mode="approved"))[0]


def test_all_across_documents_is_language_scoped_and_round_trips(tmp_path):
    revision = repeated(tmp_path, ["2026-07-01", "2026-07-02"], two_documents=True)
    q, = questions(revision)
    result = answer_revision(revision, q["id"], AllAnswer(all=True))
    result = load_revision(result.model_dump_json().encode())
    assert questions(result) == []
    assert summary(result, "unused")["accepted_ratio"] == 1
    approved = json.loads(export_bundle(result, "approved")["events.json"])[0]
    assert approved["date"] == ["2026-07-01", "2026-07-02"]
    assert {e["document_id"] for e in approved["_meta"]["fields"]["date"]["evidence"]} == {
        "doc-example", "doc-second"}


@pytest.mark.parametrize("filename", ["Hizmet ücretleri.pdf", None])
def test_pinned_source_filename_survives_loading_merge_and_question_publication(tmp_path, filename):
    runtime = accepted(tmp_path, "workspace-example")
    root = tmp_path / "inputs"
    results = [bundle(root, runtime, document="doc-a"), bundle(root, runtime, document="doc-b", price=45)]
    if filename:
        path = root / "doc-a" / "source.json"
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["filename"] = filename
        write_json(path, metadata)
    documents = load_merge_documents(root, results, runtime=runtime)
    revision = JsonMergeStore(tmp_path / "merge.json", "workspace-example").merge(
        "merged", documents, runtime=runtime)
    store = RecordsRepository(tmp_path / "packs")
    store.publish(revision)
    question, = store.list_questions("workspace-example")["items"]
    assert {o["document_name"] for o in question["options"]} == {filename or "doc-a", "doc-b"}
    revision.documents[0].document_name = "Changed after publication.pdf"
    assert {o["document_name"] for o in store.list_questions("workspace-example")["items"][0]["options"]} == {
        filename or "doc-a", "doc-b"}


def test_section_locator_is_human_readable_when_page_is_absent(review_setup):
    client, store = review_setup
    revision = fixture_revision("sections")
    revision.records[0].fields["view"].candidates[0].evidence[0].locator = "§4"
    store.publish(revision)
    assert client.get(BASE + "/questions").json()["items"][0]["options"][0]["locator"] == "§ 4"


def test_two_documents_agreeing_on_every_date_publish_a_list(tmp_path):
    # Real shape: the same nine dates appear in two documents, so the merge folds each value into
    # one candidate cited by both documents. Agreement on the whole list is not a conflict.
    values = [f"{day:02}.07.2026" for day in range(1, 10)]
    revision = repeated(tmp_path, values, two_documents=True)
    for item in revision.records[0].fields["date"].candidates:
        first = item.evidence[0]
        first.document_id, first.locator = "doc-example", "§165"
        item.evidence.append(first.model_copy(update={"document_id": "doc-second", "locator": "§43"}))
    assert questions(revision) == []
    assert summary(revision, "unused")["conflicts"] == 0
    assert project_records(revision)["events"][0]["date"] == values
