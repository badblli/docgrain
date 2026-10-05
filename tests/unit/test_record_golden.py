"""Independent neutral fixtures; no network or source/customer artifacts."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from docgrain_eval.record_golden import (
    GoldenField,
    GoldenQuestion,
    Manifest,
    align_records,
    equal,
    main,
    score_records,
    source_path,
    validate_key,
    value_match,
)


def evidence(doc="d_en", quote="32 m²", locator="page:1/cell:B2"):
    return {"document_id": doc, "locator": locator, "quote": quote}


def value(number=32, lang="en", quote="32 m²", doc="d_en"):
    return {"value": number, "lang": lang, "evidence": [evidence(doc, quote)]}


def manifest():
    sources = []
    for doc, lang, text in [("d_en", "en", "Size 32 m². Capacity 2. 35 m². No fee. 0 EUR."),
                            ("d_tr", "tr", "Alan 32 m². Ücret yok.")]:
        sources.append({"document_id": doc, "source_version_id": "sv_" + doc,
                        "path": doc + ".txt", "sha256": "0" * 64, "languages": [lang],
                        "sections": [{"locator": "page:1/cell:B2", "languages": [lang],
                                      "kind": "table", "split": "holdout", "text": text}]})
    return Manifest.model_validate({"approved_by": "reviewer", "frozen_at": "2026-10-05T10:00:00+00:00",
                                    "sources": sources, "prior_golden_sha256": [], "overlap": [],
                                    "overlap_review_note": "No earlier key for these synthetic sources.",
                                    "coverage_gaps": [], "available_collections": ["room_type"]})


def golden(**overrides):
    data = {"id": "f1", "record_id": "room_1", "collection": "room_type", "field": "size_m2",
            "primary": value(), "i18n": {"tr": value(lang="tr", doc="d_tr")},
            "tags": ["table", "unit"], "checked_by": "reviewer", "checked_at": "2026-10-05T11:00:00+00:00"}
    data.update(overrides)
    return GoldenField.model_validate(data)


def record():
    return {"id": "room_1", "type": "room_type", "size_m2": value(),
            "i18n": {"tr": {"size_m2": value(lang="tr", doc="d_tr")}}}


def question(answerable=True, **overrides):
    data = {"id": "q1", "question": "Odanın alanı kaç metrekare?", "answerable": answerable,
            "field_ids": ["f1"] if answerable else [], "expected": 32 if answerable else None,
            "evidence": [evidence()] if answerable else [], "document_ids": ["d_en"],
            "absence_reason": None if answerable else "No future-year price in reviewed sources.",
            "checked_by": "reviewer", "checked_at": "2026-10-05T11:00:00+00:00"}
    data.update(overrides)
    return GoldenQuestion.model_validate(data)


def test_correctness_denominator_keeps_omitted_fields_and_records():
    fields = [golden(), golden(id="f2", record_id="room_2")]
    report = score_records(manifest(), fields, [record()])
    assert report["overall"]["correctness"] == .5
    assert report["overall"]["expected_fields"] == 2
    assert report["overall"]["omitted_fields"] == 1
    assert report["overall"]["recall"] == .5
    assert report["per_collection"]["room_type"]["failures"]["omitted_primary"] == 1
    assert not report["d4_target"]["measurement_met"]


def test_english_selection_and_missing_translation():
    actual = record()
    actual["size_m2"] = value(lang="tr", doc="d_tr")
    actual["i18n"] = {}
    report = score_records(manifest(), [golden()], [actual])
    reasons = report["fields"][0]["reasons"]
    assert {"en_first_error", "wrong_language", "omitted_i18n"} <= set(reasons)
    assert report["overall"]["correctness"] == 0


@pytest.mark.parametrize("bad_evidence,reason", [
    ([], "missing_evidence"),
    ([evidence(quote="Invented ocean panorama")], "evidence_quote_not_in_source"),
    ([evidence(locator="page:2/cell:B2")], None),
    ([evidence(doc="d_unknown")], "evidence_unknown_document"),
    ([evidence(quote="Capacity 2.")], None),
    ([{}], "invalid_evidence"),
    ([evidence(), evidence(quote="Invented")], "evidence_quote_not_in_source"),
])
def test_every_quote_needs_approved_original_but_locator_format_is_free(bad_evidence, reason):
    actual = record()
    actual["size_m2"]["evidence"] = bad_evidence
    report = score_records(manifest(), [golden()], [actual])
    if reason:
        assert reason in report["fields"][0]["reasons"]
        assert report["overall"]["unsupported_slots"] == 1
    else:
        assert report["fields"][0]["correct"]
        assert report["overall"]["unsupported_slots"] == 0


def test_wrong_number_with_real_quote_is_incorrect():
    actual = record()
    actual["size_m2"]["value"] = 320
    report = score_records(manifest(), [golden()], [actual])
    assert "wrong_value" in report["fields"][0]["reasons"]
    assert report["overall"]["precision"] == .5


def test_normalization_is_exact_and_preserves_units_negation_and_types():
    assert equal("32\n m²", "32 m²")
    assert equal(32.0, 32)
    assert not equal(True, 1)
    assert not equal("32 m", "32 m²")
    assert not equal("not free", "free")
    assert not equal("32", 32)
    assert not equal(["a", "b"], ["a"])


def test_fallback_language_explicit_accept_and_false_zero_values():
    f = golden(primary=value(lang="tr", doc="d_tr"), i18n={})
    actual = record()
    actual["size_m2"] = value(lang="tr", doc="d_tr")
    actual["i18n"] = {}
    assert score_records(manifest(), [f], [actual])["overall"]["correctness"] == 1
    for expected in [0, False, []]:
        f = golden(primary=value(expected, quote="No fee."), i18n={})
        actual["size_m2"] = value(expected, quote="No fee.")
        assert score_records(manifest(), [f], [actual])["overall"]["correctness"] == 1
    f = golden(primary={**value("09:00-18:00", quote="No fee."), "accept": ["09.00–18.00"]}, i18n={})
    actual["size_m2"] = value("09.00–18.00", quote="No fee.")
    assert score_records(manifest(), [f], [actual])["overall"]["correctness"] == 1


def test_explicit_absence_and_out_of_key_extras():
    absent = golden(id="absent", field="price", primary=None, i18n={}, absent=True, tags=["missing"])
    actual = record()
    actual["price"] = None
    actual["features"] = value(["invented amenity"])
    report = score_records(manifest(), [golden(), absent], [actual])
    assert report["overall"]["correctness"] == 1
    assert report["overall"]["predicted_slots"] == 3
    assert report["overall"]["out_of_key_slots"] == 1
    assert report["overall"]["unsupported_slots"] == 0
    assert report["overall"]["precision"] == 1
    assert report["d4_target"]["measurement_met"]
    actual["price"] = value(10)
    report = score_records(manifest(), [golden(), absent], [actual])
    assert "unexpected_present" in report["fields"][1]["reasons"]
    assert report["overall"]["unsupported_slots"] == 1


def conflict_field():
    return golden(conflicts=[value(), value(35, quote="35 m²")], tags=["cross_document_conflict"])


def test_visible_conflict_retains_candidates_quotes_and_review_state():
    actual = record()
    actual["conflicts"] = {"size_m2": {"review_state": "needs_review",
                                          "candidates": [value(35, quote="35 m²"), value()]}}
    report = score_records(manifest(), [conflict_field()], [actual])
    assert report["overall"]["correctness"] == 1
    actual["conflicts"]["size_m2"]["candidates"][0]["evidence"] = [evidence(quote="Invented")]
    assert "wrong_conflict_candidate" in score_records(manifest(), [conflict_field()], [actual])["fields"][0]["reasons"]


def test_golden_cannot_call_equal_values_or_translations_a_conflict():
    with pytest.raises(ValueError, match="differing same-language"):
        golden(conflicts=[value(), value()])
    with pytest.raises(ValueError, match="differing same-language"):
        golden(conflicts=[value(), value(lang="tr", doc="d_tr")])
    with pytest.raises(ValueError, match="primary value"):
        golden(primary=value(40), conflicts=[value(), value(35, quote="35 m²")])


@pytest.mark.parametrize("conflict", [None, {"review_state": "accepted", "candidates": [value(), value(35, quote="35 m²")]},
                                     {"review_state": "needs_review", "candidates": [value()]}])
def test_hidden_or_silently_accepted_conflicts_fail(conflict):
    actual = record()
    actual["conflicts"] = {"size_m2": conflict}
    assert "hidden_conflict" in score_records(manifest(), [conflict_field()], [actual])["fields"][0]["reasons"]


def test_duplicate_predictions_and_wrong_collection():
    with pytest.raises(ValueError, match="duplicate predicted"):
        score_records(manifest(), [golden()], [record(), record()])
    actual = record()
    actual["type"] = "outlet"
    report = score_records(manifest(), [golden()], [actual])
    assert report["overall"]["precision"] == 0
    assert "wrong_collection" in report["fields"][0]["reasons"]


def test_unknown_records_translations_and_conflicts_are_unassessed():
    actual = record()
    actual["i18n"]["de"] = {"size_m2": value(lang="de")}
    actual["conflicts"] = {"price": {"review_state": "needs_review", "candidates": [value(10)]}}
    extra = {"id": "outlet_1", "type": "outlet", "fee": value("No fee.", quote="No fee.")}
    report = score_records(manifest(), [golden()], [actual, extra])
    assert report["overall"]["out_of_key_slots"] == 2
    assert report["overall"]["out_of_key_conflicts"] == 1
    assert report["per_collection"]["outlet"]["out_of_key_slots"] == 1
    assert report["overall"]["unsupported_slots"] == 0
    assert report["d4_target"]["measurement_met"]
    assert {row["field"] for row in report["extra_slots"]} == {"fee", "size_m2"}


def test_name_alignment_uses_document_collection_and_turkish_folding():
    rid = "d_en:room_type:standard"
    name = golden(id="name", record_id=rid, field="name",
                  primary=value("Standart Oda"), i18n={})
    size = golden(id="size", record_id=rid, i18n={})
    predicted = {"id": "d_en:room_type:9", "type": "room_type",
                 "name": value("STANDART ODA"), "size_m2": value()}
    report = score_records(manifest(), [name, size], [predicted])
    assert report["overall"]["correct_fields"] == 2
    assert report["alignment"] == [{"saved_id": predicted["id"], "golden_id": rid}]
    predicted["id"] = "d_tr:room_type:9"
    assert score_records(manifest(), [name, size], [predicted])["overall"]["omitted_fields"] == 2
    predicted["id"] = "d_en:outlet:9"
    predicted["type"] = "outlet"
    assert not score_records(manifest(), [name, size], [predicted])["alignment"]


def test_i18n_name_and_ambiguous_candidates_are_reported():
    name = golden(field="name", record_id="d_en:room_type:sea",
                  primary=value("Sea Room"), i18n={"tr": value("Deniz Oda", lang="tr", doc="d_tr")})
    predicted = [{"id": f"d_en:room_type:{i}", "type": "room_type", "name": value("DENİZ ODA")}
                 for i in (1, 2)]
    mapping, ambiguous = align_records([name], predicted)
    assert mapping == {"d_en:room_type:1": "d_en:room_type:sea"}
    assert ambiguous[0]["saved_ids"] == ["d_en:room_type:1", "d_en:room_type:2"]
    assert not score_records(manifest(), [name], predicted)["d4_target"]["measurement_met"]


def test_number_time_range_units_and_list_coverage():
    assert value_match("09.00 – 24:00", "09:00-00:00", "hours")[0]
    assert value_match("1.234,5", 1234.5, "amount")[0]
    assert value_match("18 EUR", "18 Euro", "fee")[0]
    assert value_match("person", "kişi", "unit")[0]
    assert value_match(["çift kişilik yatak", "tek kişilik"],
                       ["çift kişilik yatak veya tek kişilik"], "bed_types") == (True, (2, 2))
    assert value_match(["çift kişilik yatak"],
                       ["çift kişilik yatak veya tek kişilik"], "bed_types") == (False, (1, 2))
    assert not value_match("not free", "free", "fee")[0]


def test_quote_may_be_in_matching_context_when_original_transcription_lacks_it():
    actual = record()
    actual["size_m2"]["evidence"] = [evidence(quote="Figure 32")]
    assert "invalid_evidence" in score_records(manifest(), [golden()], [actual])["fields"][0]["reasons"]
    result = score_records(manifest(), [golden()], [actual], contexts={"d_en": "Figure 32"})
    assert result["fields"][0]["correct"]


def test_missing_list_field_stays_in_list_coverage_denominator():
    field = golden(field="bed_types", primary=value(["double bed or twin beds"]), i18n={})
    report = score_records(manifest(), [field], [record()])
    assert report["overall"]["list_items_matched"] == 0
    assert report["overall"]["list_items_expected"] == 2
    assert report["overall"]["list_coverage"] == 0


def test_exact_95_percent_boundary_and_zero_unsupported_requirement():
    fields = [golden(id=f"f{i}", record_id=f"room_{i}", i18n={}) for i in range(20)]
    records = [{"id": f"room_{i}", "type": "room_type", "size_m2": value()} for i in range(19)]
    report = score_records(manifest(), fields, records)
    assert report["overall"]["correctness"] == .95
    assert report["d4_target"]["measurement_met"]
    records.pop()
    assert not score_records(manifest(), fields, records)["d4_target"]["measurement_met"]


def test_i18n_and_conflict_candidate_duplicates_do_not_hide_missing_values():
    actual = record()
    actual["conflicts"] = {"size_m2": {"review_state": "needs_review", "candidates": [value(), value()]}}
    report = score_records(manifest(), [conflict_field()], [actual])
    assert "wrong_conflict_candidate" in report["fields"][0]["reasons"]
    actual["i18n"]["tr"]["size_m2"]["value"] = 35
    report = score_records(manifest(), [golden()], [actual])
    assert report["overall"]["correctness"] == 0
    assert report["overall"]["recall"] == .5


def test_coverage_does_not_claim_small_key_is_d4_acceptance():
    coverage = validate_key(manifest(), [golden()], [question(), question(False, id="q2")])
    assert not coverage["ready"]
    assert coverage["fields"] == 1
    assert coverage["questions"] == 2
    assert coverage["unanswerable"] == 1


def test_contamination_and_missing_languages_are_reported():
    m = manifest()
    m.overlap = [type(question().evidence[0]).model_validate(evidence())]
    coverage = validate_key(m, [golden(i18n={})], [])
    assert coverage["overlapping_holdout_sections"] == 1
    assert coverage["missing_languages"] == ["tr"]
    assert not coverage["requirements"]["no_prior_golden_holdout_overlap"]


@pytest.mark.parametrize("change", ["unfrozen", "earlier", "bad_quote", "duplicate"])
def test_golden_provenance_validation(change):
    m, f = manifest(), golden()
    if change == "unfrozen":
        m.frozen_at = None
    if change == "earlier":
        f.checked_at = "2026-10-05T09:00:00+00:00"
    if change == "bad_quote":
        f.primary.evidence[0].quote = "Not in original"
    with pytest.raises(ValueError):
        validate_key(m, [f, f] if change == "duplicate" else [f], [])


def test_question_requires_absence_audit_or_answer_fields():
    with pytest.raises(ValueError):
        question(False, absence_reason=None)
    with pytest.raises(ValueError):
        question(field_ids=[])
    with pytest.raises(ValueError, match="unknown"):
        validate_key(manifest(), [golden()], [question(field_ids=["unknown"])])
    with pytest.raises(ValueError, match="referenced fields"):
        validate_key(manifest(), [golden()], [question(evidence=[evidence(quote="Capacity 2.")])])


def test_full_synthetic_coverage_gate():
    m = manifest()
    second_english = m.sources[0].model_copy(deep=True)
    second_english.document_id = "d_en2"
    second_english.source_version_id = "sv_en2"
    m.sources.append(second_english)
    fields = [golden(id=f"f{i}", record_id=f"room_{i}") for i in range(98)]
    fields += [golden(id="f98", field="fee", primary=value(0, quote="No fee."), i18n={}, tags=["negative"]),
               golden(id="f99", field="price", primary=None, i18n={}, absent=True, tags=["missing"])]
    fields[1] = golden(id="f1", record_id="room_1", conflicts=[value(), value(35, quote="35 m²", doc="d_en2")],
                       tags=["cross_document_conflict"])
    questions = [question(id=f"q{i}", field_ids=["f0"]) for i in range(32)]
    questions += [question(False, id=f"u{i}") for i in range(8)]
    coverage = validate_key(m, fields, questions)
    assert coverage["ready"]
    assert coverage["fields"] == 100 and coverage["questions"] == 40


@pytest.mark.parametrize("directory", ["sonDB", "SONDB", "yeni db"])
def test_forbidden_directories_rejected_without_opening(directory, tmp_path):
    with pytest.raises(ValueError, match="forbidden"):
        source_path(str(tmp_path / directory / "source.txt"), tmp_path)


def write_inputs(tmp_path):
    m = manifest()
    for source in m.sources:
        path = tmp_path / source.path
        path.write_text(source.sections[0].text, encoding="utf-8")
        source.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    paths = {name: tmp_path / name for name in ["manifest.json", "fields.jsonl", "questions.jsonl", "records.json"]}
    paths["manifest.json"].write_text(m.model_dump_json(), encoding="utf-8")
    paths["fields.jsonl"].write_text(golden().model_dump_json() + "\n", encoding="utf-8")
    paths["questions.jsonl"].write_text(question().model_dump_json() + "\n", encoding="utf-8")
    paths["records.json"].write_text(json.dumps({"records": [record()]}), encoding="utf-8")
    return paths


def test_cli_freeze_receipts_score_exit_and_no_network(tmp_path, monkeypatch, capsys):
    def denied(*args, **kwargs):
        pytest.fail("offline measurement attempted network access")

    monkeypatch.setattr("socket.socket", denied)
    paths = write_inputs(tmp_path)
    args = ["--manifest", str(paths["manifest.json"]), "--golden", str(paths["fields.jsonl"]),
            "--questions", str(paths["questions.jsonl"])]
    assert main(["validate", *args]) == 2
    out = tmp_path / "results"
    assert main(["score", *args, "--records", str(paths["records.json"]), "--out", str(out)]) == 2
    report = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert report["overall"]["correctness"] == 1
    assert report["d4_target"]["measurement_met"]
    assert not report["d4_target"]["criteria_met"]  # Coverage, not JSON validity, gates the result.
    assert report["receipts"]["records_sha256"]
    assert main(["score", *args, "--records", str(paths["records.json"]), "--out", str(out)]) == 1
    draft = copy.deepcopy(json.loads(paths["manifest.json"].read_text(encoding="utf-8")))
    draft["frozen_at"] = None
    paths["manifest.json"].write_text(json.dumps(draft), encoding="utf-8")
    frozen = tmp_path / "frozen.json"
    assert main(["freeze", "--manifest", str(paths["manifest.json"]), "--out", str(frozen)]) == 0
    assert Path(json.loads(frozen.read_text(encoding="utf-8"))["sources"][0]["path"]).is_absolute()
    assert main(["freeze", "--manifest", str(paths["manifest.json"]), "--out", str(frozen)]) == 1
    assert "32 m" not in capsys.readouterr().out


def test_cli_changed_source_and_invalid_golden_do_not_leak_input(tmp_path, capsys):
    paths = write_inputs(tmp_path)
    args = ["validate", "--manifest", str(paths["manifest.json"]), "--golden", str(paths["fields.jsonl"]),
            "--questions", str(paths["questions.jsonl"])]
    private = "private source text"
    paths["fields.jsonl"].write_text(json.dumps({"secret": private}), encoding="utf-8")
    assert main(args) == 1
    assert private not in capsys.readouterr().err
    (tmp_path / "d_en.txt").write_text("changed", encoding="utf-8")
    assert main(args) == 1


def test_cli_context_receipt_and_quote_verification(tmp_path):
    paths = write_inputs(tmp_path)
    records = json.loads(paths["records.json"].read_text(encoding="utf-8"))
    records["records"][0]["size_m2"]["evidence"] = [evidence(quote="Figure 32")]
    paths["records.json"].write_text(json.dumps(records), encoding="utf-8")
    context = tmp_path / "context.md"
    context.write_text("Figure 32", encoding="utf-8")
    out = tmp_path / "result"
    assert main(["score", "--manifest", str(paths["manifest.json"]),
                 "--golden", str(paths["fields.jsonl"]), "--questions", str(paths["questions.jsonl"]),
                 "--records", str(paths["records.json"]), "--context", f"d_en={context}",
                 "--out", str(out)]) == 2
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall"]["correct_fields"] == 1
    assert summary["receipts"]["contexts_sha256"]["d_en"] == hashlib.sha256(context.read_bytes()).hexdigest()
