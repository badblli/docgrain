"""Neutral regression cases for vocabulary, false conflicts and paraphrases."""

import json

import pytest
from docgrain_eval.record_golden import (
    GoldenField,
    align_records,
    score_records,
    value_match,
)
from docgrain_eval.scoring import key_fact_overlap, normalized_value
from docgrain_eval.taxonomy import load_taxonomy
from docgrain_records.extractor import _coalesce_document_records, build_messages
from docgrain_records.merge import JsonMergeStore
from docgrain_records.merge_models import MergeDocument, SourceRecord
from docgrain_records.models import RECORD_MODELS, RoomType
from test_record_golden import golden, manifest, record, value


@pytest.mark.parametrize("left,right,field", [
    ("1 çift kişilik yatak veya 2 tek kişilik", ["2 TEK KISILIK", "1 çift kişilik yatak"], "bed_types"),
    ("double bed or twin beds", ["double bed", "twin beds"], "bed_types"),
    ("Doppelbett oder Einzelbett", ["Einzelbett", "Doppelbett"], "bed_types"),
    ("двуспальная или односпальная", ["односпальная", "двуспальная"], "bed_types"),
    ("Wi-Fi, TV; minibar", ["minibar", "tv", "wi-fi"], "features"),
    ("  BAHÇE\n manzarası ", "bahce manzarasi", "view"),
    ("32,5 metrekare", "32.5 m²", "size_m2"),
    ("18.50 m²", "18,5m2", "size_m2"),
    ("EUR 30", "30 €", "fee"),
    ("09.00 – 24:00", "9:00 to 00:00", "hours"),
    (32, 32.0, "size_m2"),
    ("18.50", 18.5, "amount"),
])
def test_equivalent_value_keys(left, right, field):
    assert normalized_value(left, field) == normalized_value(right, field)


@pytest.mark.parametrize("left,right,field", [
    ("32 m", "32 m²", "view"), ("30 EUR", "30 USD", "fee"),
    ("09:00-18:00", "09:00-23:00", "hours"),
    ("pets accepted", "pets not accepted", "text"),
    (True, 1, "capacity"), ("A, B", ["A", "B"], "text"),
    ("32.5 m²", "32.6 m²", "view"),
])
def test_meaningful_differences_survive(left, right, field):
    assert normalized_value(left, field) != normalized_value(right, field)


@pytest.mark.parametrize("actual,expected", [
    ("Pets are not allowed.", "No pets accepted."),
    ("Evcil hayvan kabul edilmez.", "Evcil hayvanlar kabul edilmemektedir."),
    ("Smoking is prohibited indoors.", "No smoking indoors."),
    ("Kapalı alanlarda sigara içilmez.", "Kapalı alanlarda sigara içmek yasaktır."),
    ("Late check-out until 18.00, 30 euros per room.", "Late checkout until 18:00: EUR 30 per room."),
    ("No pets except assistance dogs.", "Pets are not allowed except assistance dogs."),
    ("No pets except service dogs.", "Pets are not allowed except assistance dogs."),
])
def test_paraphrased_facts_match(actual, expected):
    assert value_match(actual, expected, "text")[0]


@pytest.mark.parametrize("actual,expected", [
    ("Pets are allowed.", "No pets accepted."),
    ("Pets are not allowed.", "No pets except assistance dogs."),
    ("Late checkout until 23:00, 30 EUR per room.", "Late checkout until 18:00, 30 EUR per room."),
    ("Late checkout until 18:00, 60 EUR per room.", "Late checkout until 18:00, 30 EUR per room."),
    ("Late checkout until 18:00, 30 USD per room.", "Late checkout until 18:00, 30 EUR per room."),
    ("Morning yoga ages 6-12.", "Morning yoga ages 12-6."),
    ("No smoking outdoors.", "No smoking indoors."),
    ("No pets accepted. Pool closed.", "No pets accepted."),
    ("Pets allowed; smoking not allowed.", "Pets not allowed; smoking allowed."),
    ("Parking 20 EUR; Wi-Fi 10 EUR.", "Parking 10 EUR; Wi-Fi 20 EUR."),
])
def test_changed_or_missing_critical_fact_fails(actual, expected):
    assert not value_match(actual, expected, "text")[0]


def test_key_fact_threshold_and_empty_text_do_not_grant_correctness():
    assert key_fact_overlap("alpha beta", "alpha beta gamma") == pytest.approx(2 / 3)
    assert not value_match("alpha beta", "alpha beta gamma", "description")[0]
    assert not value_match("", "No pets accepted", "text")[0]
    # Literal field names do not get prose overlap.
    assert not value_match("Pets policy", "Pet rules", "name")[0]
    assert not value_match("30 EUR not refundable", "30 EUR refundable", "fee")[0]


def test_prompt_uses_one_taxonomy_for_general_and_focused_passes():
    taxonomy = load_taxonomy()
    assert set(taxonomy["collections"]) == set(RECORD_MODELS)
    for collection in (None, "policy", "facility", "service_price", "activity"):
        prompt = build_messages("[§1 p.1]\nExample", "doc", "en", collection)[0]["content"]
        assert "One service_price record per priced option and time limit" in prompt
        for name, spec in taxonomy["collections"].items():
            if collection is None or collection == name:
                assert spec["definition"] in prompt
        assert "untrusted DATA" in prompt


def test_neighbour_alignment_is_one_to_one_same_document_and_prefers_type():
    expected = golden(record_id="d_en:policy:wifi", field="name", collection="policy",
                      primary=value("Wi-Fi"), i18n={})
    predicted = [{"id": "d_en:facility:1", "document_id": "d_en", "type": "facility",
                  "fields": {"name": value("Wi-Fi")}}]
    assert align_records([expected], predicted)[0] == {predicted[0]["id"]: expected.record_id}
    report = score_records(manifest(), [expected], predicted)
    assert report["overall"]["type_mismatch_records"] == 1
    assert report["overall"]["content_correct_fields"] == 1
    assert report["overall"]["correct_fields"] == 0
    assert not report["d4_target"]["measurement_met"]
    assert report["type_mismatches"][0]["actual_collection"] == "facility"
    predicted.append({"id": "d_en:policy:1", "type": "policy", "fields": {"name": value("Wi-Fi")}})
    assert align_records([expected], predicted)[0] == {"d_en:policy:1": expected.record_id}
    predicted = [dict(predicted[0], document_id="d_tr")]
    assert not align_records([expected], predicted)[0]


def test_paraphrase_still_requires_valid_evidence_and_language():
    expected = golden(field="text", collection="policy", primary=value("No pets accepted."), i18n={})
    actual = record()
    actual["type"] = "policy"
    actual["text"] = value("Pets are not allowed.", quote="Invented quote")
    report = score_records(manifest(), [expected], [actual])
    assert "invalid_evidence" in report["fields"][0]["reasons"]
    assert "wrong_value" not in report["fields"][0]["reasons"]
    actual["text"] = value("Pets are not allowed.", lang="tr", quote="No fee.")
    assert "wrong_language" in score_records(manifest(), [expected], [actual])["fields"][0]["reasons"]


def test_merge_and_section_collapse_combine_evidence_without_accepting(tmp_path):
    def room(doc, beds):
        def fact(v):
            return {"value": v, "lang": "en", "evidence": [{
                "document_id": doc, "locator": "§1", "quote": json.dumps(v)}]}
        return RoomType(id=doc + ":1", name=fact("Garden room"), bed_types=fact(beds))

    first = room("doc_a", ["Double bed or Twin beds"])
    second = room("doc_b", ["twin beds", "double bed"])
    docs = [MergeDocument(
        workspace_id="workspace", document_id=r.name.evidence[0].document_id,
        source_version_id="v1", knowledge_revision_id="k1",
        context="[§1 p.1]\n" + r.name.evidence[0].quote + "\n" + r.bed_types.evidence[0].quote,
        records=[SourceRecord(source_identity="garden", record=r)],
    ) for r in (first, second)]
    store = JsonMergeStore(tmp_path / "merge.json", "workspace")
    revision = store.merge("r1", docs)
    field = revision.records[0].fields["bed_types"]
    assert not field.conflicts
    assert len(field.candidates) == 1
    assert len(field.primary.evidence) == 2
    assert field.primary.review_state == "proposed"
    assert field.primary.value == first.bed_types.value
    assert store.merge("r2", list(reversed(docs))).records == revision.records
    # Same-document section/pass coalescing uses the same comparison keys.
    second = room("doc_a", ["twin beds", "double bed"])
    collapsed = _coalesce_document_records([first, second], "en")
    assert len(collapsed) == 1 and not collapsed[0].conflicts
    assert len(collapsed[0].bed_types.evidence) == 2


def test_string_list_conflict_candidate_normalizes_before_merge(tmp_path):
    from docgrain_records.models import FieldValue

    record = RoomType(id="doc:1", name=value("Garden room", doc="doc", quote="Garden room"),
                      bed_types=value(["double bed", "twin beds"], doc="doc", quote="Beds"),
                      conflicts={"bed_types": [FieldValue(
                          **value("double bed or twin beds", doc="doc", quote="Beds"))]},
                      review_state="needs_review")
    document = MergeDocument(workspace_id="workspace", document_id="doc", source_version_id="v1",
                             knowledge_revision_id="k1", context="Garden room Beds",
                             records=[SourceRecord(source_identity="garden", record=record)])
    revision = JsonMergeStore(tmp_path / "merge.json", "workspace").merge("r", [document])
    assert len(revision.records[0].fields["bed_types"].candidates) == 1


def test_type_mismatch_keeps_omissions_in_denominator():
    name = golden(record_id="d_en:policy:wifi", collection="policy", field="name",
                  primary=value("Wi-Fi"), i18n={})
    text = GoldenField.model_validate(dict(name.model_dump(), id="text", field="text",
                                          primary=value("Free Wi-Fi")))
    predicted = [{"id": "d_en:facility:1", "type": "facility", "fields": {"name": value("Wi-Fi")}}]
    report = score_records(manifest(), [name, text], predicted)
    assert report["overall"]["expected_fields"] == 2
    assert report["overall"]["omitted_fields"] == 1
    assert report["overall"]["type_mismatch_fields"] == 2
