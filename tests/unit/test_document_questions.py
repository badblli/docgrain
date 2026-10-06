"""Document choices preserve all citations and publish only that source's values."""

import json

import pytest
import test_review_decisions as review_tests
from docgrain_records.merge_models import FactCandidate
from docgrain_records.review import questions, summary
from test_records_export import candidate, fixture_revision
from test_review_decisions import BASE, answer

review_setup = review_tests.setup


def document_revision():
    revision = fixture_revision("documents")
    first = revision.documents[0]
    first.document_name = "Oda rehberi.pdf"
    revision.documents.extend([
        first.model_copy(update={"document_id": "doc-second", "document_name": "Oda listesi.txt"}),
        first.model_copy(update={"document_id": "doc-third", "document_name": "Yeni liste.pdf"}),
    ])
    values = revision.records[0].fields["view"].candidates
    # A shared value belongs to both documents; the second source has two quotes for it.
    values[0].evidence.extend([
        values[0].evidence[0].model_copy(update={"document_id": "doc-second", "locator": "line 2"}),
        values[0].evidence[0].model_copy(update={"document_id": "doc-second", "locator": "line 8"}),
    ])
    values[1].evidence[0].document_id = "doc-second"
    third = candidate("Forest", "needs_review", id="view-c")
    third["evidence"][0]["document_id"] = "doc-third"
    values.extend([
        FactCandidate.model_validate(third),
        FactCandidate.model_validate(candidate("Old", "rejected", id="view-old")),
        FactCandidate.model_validate(candidate("Bahçe", "needs_review", lang="tr", id="view-tr")),
    ])
    return revision


def test_question_exposes_every_document_and_quote_with_deterministic_order():
    revision = document_revision()
    question = next(q for q in questions(revision) if q["field"] == "view" and q["lang"] == "en")
    assert [(o["candidate_id"], o["document_id"], o["locator"]) for o in question["options"]] == [
        ("view-a", "doc-example", "s. 1"),
        ("view-a", "doc-second", "line 2"),
        ("view-a", "doc-second", "line 8"),
        ("view-b", "doc-second", "s. 1"),
        ("view-c", "doc-third", "s. 1"),
    ]
    assert [o["quote"] for o in question["options"]] == ["Garden", "Garden", "Garden", "Sea", "Forest"]
    for item in revision.records[0].fields["view"].candidates:
        item.evidence.reverse()
    assert next(q for q in questions(revision) if q["id"] == question["id"]) == question


@pytest.mark.parametrize("document,expected,states,selected", [
    ("doc-example", "Garden", ["accepted", "rejected", "rejected"], ["view-a"]),
    ("doc-second", ["Garden", "Sea"], ["accepted", "accepted", "rejected"], ["view-a", "view-b"]),
    ("doc-third", "Forest", ["rejected", "rejected", "accepted"], ["view-c"]),
])
def test_document_answer_scalar_or_list_is_evidenced_immutable_and_language_scoped(
        review_setup, document, expected, states, selected):
    client, store = review_setup
    revision = document_revision()
    store.publish(revision)
    before = store.read("workspace-example", revision.id, "rooms")
    question = next(q for q in client.get(BASE + "/questions").json()["items"]
                    if q["field"] == "view" and q["lang"] == "en")
    response = answer(client, question, {"document_id": document})
    assert response.status_code == 200
    child = response.json()["revision_id"]
    assert response.json()["remaining"] == 2
    for mode in ("preview", "approved"):
        row = next(r for r in client.get(
            BASE + f"/revisions/{child}/collections/rooms?mode={mode}").json() if r["id"] == "rec-room")
        assert row["view"] == expected
        evidence = row["_meta"]["fields"]["view"]["evidence"]
        assert any(e["document_id"] == document for e in evidence)
        assert all(e["quote"] for e in evidence)
    result = store._source("workspace-example")
    assert result.parent_id == revision.id and result.lineage_id == revision.id
    field = result.records[0].fields["view"]
    assert [c.review_state for c in field.candidates] == states + ["rejected", "needs_review"]
    assert field.multi_value_languages == (["en"] if isinstance(expected, list) else [])
    assert result.history[-1].candidate_ids == selected
    assert result.history[-1].all is False
    assert store.read("workspace-example", revision.id, "rooms") == before
    assert "view" not in json.loads(store.read(
        "workspace-example", revision.id, "rooms", mode="approved"))[0]
    assert answer(client, question, {"document_id": document}).status_code == 409


def test_document_cannot_choose_evidence_from_another_language(review_setup):
    client, store = review_setup
    revision = document_revision()
    values = revision.records[0].fields["view"].candidates
    values[2].review_state = "rejected"
    values[-1].evidence[0].document_id = "doc-third"
    store.publish(revision)
    question = next(q for q in client.get(BASE + "/questions").json()["items"]
                    if q["field"] == "view" and q["lang"] == "en")
    assert answer(client, question, {"document_id": "doc-third"}).status_code == 422
    assert store.list_revisions("workspace-example")[0] == revision.id


def test_proposed_records_without_questions_are_never_counted_as_approved():
    revision = fixture_revision()
    for record in revision.records:
        for field in record.fields.values():
            for item in field.candidates:
                item.review_state = "proposed"
            field.candidates = field.candidates[:1]
    result = summary(revision, "unused")
    assert result["conflicts"] == result["needs_review"] == 0
    assert all(c["accepted_records"] == c["pending_records"] == 0 for c in result["collections"])


def test_document_answer_preserves_native_lists_and_disallowed_all_never_publishes(review_setup):
    client, store = review_setup
    question = next(q for q in client.get(BASE + "/questions").json()["items"]
                    if q["field"] == "bed_types")
    assert question["allow_all"] is False
    assert answer(client, question, {"all": True}).status_code == 422
    assert store.list_revisions("workspace-example") == ["r1"]
    result = answer(client, question, {"document_id": "doc-example"})
    assert result.status_code == 200
    row = client.get(BASE + f"/revisions/{result.json()['revision_id']}"
                     "/collections/rooms?mode=approved").json()[0]
    assert row["bed_types"] == ["double"]
