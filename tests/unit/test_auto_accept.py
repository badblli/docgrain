"""WP111 / karar 20: verified agreeing values are accepted by a rule; real conflicts stay questions."""

import json
import socket

import pytest
from docgrain_api.records_repository import PackMissing, RecordsRepository
from docgrain_records.auto_accept import (
    RULE_AGREEING,
    RULE_FORMAT,
    RULE_NEAR,
    RULE_SINGLE,
    apply_review_rules,
    human_accepted,
)
from docgrain_records.export import export_bundle
from docgrain_records.merge_models import MergeRevision
from docgrain_records.normalize import format_key, mentions, near_identical, same_value
from docgrain_records.review import (
    CandidateAnswer,
    EditAnswer,
    answer_revision,
    auto_accepted,
    questions,
    summary,
)

WORKSPACE = "workspace-example"
DOCUMENTS = ("doc-a", "doc-b")
LONG = "Cilt bakımında konsantre bitki özleri kullanılır ve bakım 60 dakika sürer."
LONG_OCR = "Cilt bakımında konsanire bitki özleri kullanılır ve bakım 60 dakika sürer."


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("auto acceptance must never use network or models")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def evidence(document, quote):
    return {"document_id": document, "source_version_id": document + "-s1",
            "knowledge_revision_id": document + "-k1", "locator": "§1 p.1", "quote": quote}


def candidate(id, value, *quotes, state="proposed", lang="en"):
    """quotes: (document, quote) pairs; default one quote of the value in doc-a."""
    quotes = quotes or (("doc-a", str(value)),)
    return {"id": id, "value": value, "lang": lang, "review_state": state,
            "evidence": [evidence(document, quote) for document, quote in quotes]}


def field(*candidates):
    # The merge marks same-language alternatives needs_review; single values stay proposed.
    if len(candidates) > 1:
        for item in candidates:
            item["review_state"] = "needs_review"
    return {"primary_lang": "en", "candidates": list(candidates)}


def revision(**records):
    return MergeRevision.model_validate({
        "workspace_id": WORKSPACE, "id": "r1",
        "documents": [{"document_id": d, "source_version_id": d + "-s1",
                       "knowledge_revision_id": d + "-k1", "document_name": d + ".pdf"}
                      for d in DOCUMENTS],
        "records": [{"id": key, "type": kind, "fields": fields}
                    for key, (kind, fields) in records.items()],
    })


def states(revision, record, name):
    merged = next(r for r in revision.records if r.id == record).fields[name]
    return {c.id: c.review_state for c in merged.candidates}


def reviewers(revision):
    return {(d.record_id, d.field, d.candidate_id): (d.action, d.reviewer) for d in revision.decisions}


def fixture():
    return revision(
        room=("room_type", {
            "name": field(candidate("name", "Garden Room", ("doc-a", "Garden Room: 32 m2"))),
            "size_m2": field(candidate("size-32", 32, ("doc-a", "Garden Room: 32 m2")),
                             candidate("size-36", 36, ("doc-b", "Garden Room: 36 m2"))),
            "view": field(candidate("view", "Sea", ("doc-a", "Garden view"))),  # quote lacks value
            "capacity": field(candidate("cap-a", 2, ("doc-a", "capacity 2"), ("doc-b", "capacity 2"))),
        }),
        bar=("outlet", {
            "name": field(candidate("bar", "Pool Bar", ("doc-a", "Pool Bar"), ("doc-b", "Pool Bar"))),
            "hours": field(candidate("hours-dash", "10:00-18:00", ("doc-a", "Pool Bar 10:00-18:00")),
                           candidate("hours-slash", "10:00 / 18:00", ("doc-b", "Pool Bar 10:00 / 18:00"))),
            "fee": field(candidate("fee-18", "10:00-18:00", ("doc-a", "Kids club 10:00-18:00")),
                         candidate("fee-19", "10:00-19:00", ("doc-b", "Kids club 10:00-19:00"))),
        }),
        spa=("facility", {
            "name": field(candidate("spa", "Spa", ("doc-a", "Spa"), ("doc-b", "Spa"))),
            "fee": field(candidate("fee-a", LONG, ("doc-a", LONG), ("doc-b", LONG)),
                         candidate("fee-b", LONG_OCR, ("doc-b", LONG_OCR))),
        }),
    )


def test_normalized_comparison_rules():
    assert same_value("10:00 / 18:00", "10:00-18:00")
    assert same_value("10.00 – 18.00", "10:00-18:00")
    assert same_value("25-27 m 2", "25–27 m²")
    assert same_value("24 saat", "24  Saat")
    assert same_value("İSTANBUL", "istanbul") and same_value("KAPALI", "Kapalı")
    assert same_value("Açık büfe.", "açık büfe")
    assert same_value(32, 32.0)
    # Different numbers, times, dates and units never merge.
    for left, right in [("10:00", "11:00"), ("10:00-18:00", "10:00-19:00"), ("25 m2", "27 m2"),
                        ("20%", "20"), ("1/2 porsiyon", "1-2 porsiyon"), (32, 36),
                        ("2026-06-01", "2026-06-10"), ("12 EUR", "12 USD")]:
        assert not same_value(left, right), (left, right)
    assert format_key(["b", "a"], "features") == format_key(["a", "b."], "features")


def test_near_identical_long_text_only_for_typing_slips():
    assert near_identical(LONG, LONG_OCR)
    assert not near_identical(LONG, LONG.replace("60", "90"))  # numbers must match
    assert not near_identical("konsantre", "konsanire")  # short values are never near-identical
    negated = "Otelimizde evcil hayvan kabul edilir, lütfen resepsiyona önceden bilgi veriniz."
    assert not near_identical(negated, negated.replace("edilir", "edilmez"))
    priced = "Masaj ücretsiz olarak sunulur ve rezervasyon resepsiyondan yapılır."
    assert not near_identical(priced, priced.replace("ücretsiz", "ücretli"))
    assert not near_identical(priced, priced.replace(" ve ", " "))  # a dropped word is not a slip
    breakfast = "Breakfast is included in the room rate and served in the main restaurant daily."
    assert not near_identical(breakfast, breakfast.replace("included", "excluded"))
    assert near_identical(breakfast, breakfast.replace("restaurant", "restaurnt"))
    rated = "Prices are quoted inclusively of taxes and service charges for all guests staying."
    assert not near_identical(rated, rated.replace("inclusively", "exclusively"))


def test_quote_mentions_value_literally_or_formatting_equal():
    assert mentions("Pool Bar 10:00 / 18:00", "10:00-18:00")
    assert mentions("capacity 2", 2) and mentions("Pets allowed", True)
    assert not mentions("Garden view", "Sea") and not mentions("", "Sea")


def test_single_and_agreeing_sources_are_accepted_by_rule_and_published():
    result, audit = apply_review_rules(fixture())
    decided = reviewers(result)
    # Single source, verified, no other candidate.
    assert states(result, "room", "name") == {"name": "accepted"}
    assert decided[("room", "name", "name")] == ("accepted", RULE_SINGLE)
    # One value cited by two documents.
    assert decided[("room", "capacity", "cap-a")] == ("accepted", RULE_AGREEING)
    # Two documents, equal after normalization: accepted, no question, variant recorded.
    assert states(result, "bar", "hours") == {"hours-dash": "accepted", "hours-slash": "rejected"}
    assert decided[("bar", "hours", "hours-dash")] == ("accepted", RULE_AGREEING)
    assert decided[("bar", "hours", "hours-slash")] == ("rejected", RULE_FORMAT)
    assert {item["reviewer"] for item in audit} >= {RULE_SINGLE, RULE_AGREEING, RULE_FORMAT, RULE_NEAR}
    approved = {row["id"]: row for row in json.loads(export_bundle(result, "approved")["outlets.json"])}
    assert approved["bar"]["hours"] == "10:00-18:00"
    assert approved["bar"]["_meta"]["fields"]["hours"]["review_state"] == "accepted"
    rooms = {row["id"]: row for row in json.loads(export_bundle(result, "approved")["rooms.json"])}
    assert rooms["room"]["name"] == "Garden Room" and rooms["room"]["capacity"] == 2
    assert "size_m2" not in rooms["room"] and "view" not in rooms["room"]


def test_real_conflicts_and_unverified_evidence_stay_questions():
    result, _ = apply_review_rules(fixture())
    # Different numbers and different times: conflict questions, nothing accepted.
    assert set(states(result, "room", "size_m2").values()) == {"needs_review"}
    assert set(states(result, "bar", "fee").values()) == {"needs_review"}
    # The quote does not state the value: verifier doubt -> still a question.
    assert states(result, "room", "view") == {"view": "needs_review"}
    asked = {(q["record_id"], q["field"]): q["kind"] for q in questions(result)}
    assert asked == {("room", "size_m2"): "conflict", ("bar", "fee"): "conflict",
                     ("room", "view"): "needs_review"}
    report = summary(result, "2026-10-09T00:00:00+00:00")
    assert (report["conflicts"], report["needs_review"], report["unsupported_fields"]) == (2, 1, 0)


def test_near_identical_long_text_keeps_one_value_and_a_variant():
    result, _ = apply_review_rules(fixture())
    assert states(result, "spa", "fee") == {"fee-a": "accepted", "fee-b": "rejected"}
    decided = reviewers(result)
    assert decided[("spa", "fee", "fee-a")] == ("accepted", RULE_AGREEING)  # better sourced: 2 docs
    action, rule = decided[("spa", "fee", "fee-b")]
    assert (action, rule) == ("rejected", RULE_NEAR)
    reason = next(d.reason for d in result.decisions if d.candidate_id == "fee-b")
    assert "fee-a" in reason
    assert not any(q["field"] == "fee" and q["record_id"] == "spa" for q in questions(result))
    # The variant and its evidence stay in the revision for audit.
    variant = next(c for r in result.records if r.id == "spa" for c in r.fields["fee"].candidates
                   if c.id == "fee-b")
    assert variant.value == LONG_OCR and variant.evidence[0].quote == LONG_OCR


def test_one_document_listing_several_times_is_accepted_as_a_list():
    source = revision(club=("activity", {
        "name": field(candidate("club", "Kids Club")),
        "schedule": field(candidate("t1", "10:00", ("doc-a", "10:00")),
                          candidate("t2", "14:00", ("doc-a", "14:00"))),
    }))
    result, _ = apply_review_rules(source)
    assert states(result, "club", "schedule") == {"t1": "accepted", "t2": "accepted"}
    rows = json.loads(export_bundle(result, "approved")["activities.json"])
    assert rows[0]["schedule"] == ["10:00", "14:00"]


def test_user_edit_and_existing_decisions_are_left_alone():
    source = fixture()
    record = next(r for r in source.records if r.id == "room")
    record.fields["name"].candidates[0].review_state = "rejected"
    result, audit = apply_review_rules(source)
    assert states(result, "room", "name") == {"name": "rejected"}
    assert not any(item["field"] == "name" and item["record_id"] == "room" for item in audit)


def test_rule_values_are_listed_and_correctable_and_do_not_count_as_human(tmp_path):
    result, _ = apply_review_rules(fixture())
    assert not human_accepted(result)
    items = {(q["record_id"], q["field"]): q for q in auto_accepted(result)}
    assert set(items) == {("room", "name"), ("room", "capacity"), ("bar", "name"),
                          ("bar", "hours"), ("spa", "name"), ("spa", "fee")}
    hours = items[("bar", "hours")]
    assert hours["kind"] == "auto_accepted" and hours["reviewer"] == RULE_AGREEING
    assert [(o["candidate_id"], o["accepted"], o["reviewer"]) for o in hours["options"]] == [
        ("hours-dash", True, RULE_AGREEING), ("hours-slash", False, RULE_FORMAT)]
    assert hours["id"] not in {q["id"] for q in questions(result)}
    # A person picks the recorded variant instead of the rule's choice.
    changed = answer_revision(result, hours["id"], CandidateAnswer(candidate_id="hours-slash"))
    assert states(changed, "bar", "hours") == {"hours-dash": "rejected", "hours-slash": "accepted"}
    assert changed.history[-1].candidate_id == "hours-slash" and human_accepted(changed)
    assert ("bar", "hours") not in {(q["record_id"], q["field"]) for q in auto_accepted(changed)}
    # A correction through the repository answer path, by the slot ID.
    store = RecordsRepository(tmp_path)
    store.publish(result)
    listed = store.list_auto_accepted(WORKSPACE)
    assert listed["total"] == 6
    name = next(q for q in listed["items"] if (q["record_id"], q["field"]) == ("room", "name"))
    answered = store.answer_question(WORKSPACE, name["id"], EditAnswer(value="Garden Suite", note="fix"))
    newest = store._source(WORKSPACE, answered["revision_id"])
    accepted = [c for r in newest.records if r.id == "room" for c in r.fields["name"].candidates
                if c.review_state == "accepted"]
    assert [c.value for c in accepted] == ["Garden Suite"]
    with pytest.raises(PackMissing):
        store.answer_question(WORKSPACE, "q_" + "0" * 64, EditAnswer(value="x", note=""),
                              revision=newest.id)
