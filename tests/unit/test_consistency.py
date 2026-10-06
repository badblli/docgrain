"""WP53 adversarial offline checks; all inputs are neutral synthetic data."""

import copy
import json
import runpy
from pathlib import Path

import httpx
import pytest
from docgrain_eval.cli import main
from docgrain_eval.consistency import (
    company_summary,
    coverage,
    load_run,
    load_sources,
    normalized_name,
    stability,
    support,
)
from docgrain_records.match_merge import write_json


@pytest.fixture
def companies(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("offline evaluation attempted a network call")
    monkeypatch.setattr(httpx.Client, "send", no_network)
    example = Path(__file__).parents[2] / "docs" / "examples" / "stability_synthetic.py"
    paths = runpy.run_path(str(example))["generate"](tmp_path)
    return tmp_path, paths


def merged(companies):
    root, paths = companies
    run = load_run(paths[0])
    sources = load_sources(paths[0] / "sources", run.workspace)
    return root, paths, run, sources


def test_four_companies_actual_extract_merge_cli_and_reports(companies, capsys):
    root, paths = companies
    report = json.loads((root / "companies.json").read_text(encoding="utf-8"))
    assert len(report["companies"]) == 4
    assert [c["collections"][0]["key"] for c in report["companies"]] == [
        "rooms", "services", "classes", "products"]
    for company in report["companies"]:
        assert company["collections"][0]["records"] == 2
        assert company["support"]["published_fields"] == 4
        assert company["support"]["unsupported_field_rate"] == 0
        assert company["coverage"]["rate"] == 1
        assert company["bundle"]["documents_missing_from_run"] == 0
        assert company["accuracy"]["status"] == "not_measured"
    for path in paths:
        result = json.loads((path.parent / "stability" / "stability.json").read_text())
        assert result["records"] == {"identical": 2, "total": 2, "rate": 1}
        assert result["fields"] == {"identical": 4, "total": 4, "rate": 1}
        assert result["input_verification"] == "pins_only"
    outputs = capsys.readouterr().out + (root / "companies.md").read_text(encoding="utf-8")
    assert "Garden" not in outputs and "River" not in outputs
    assert all(str(path) not in outputs for path in paths)


def test_stability_ignores_ids_order_derived_views_but_not_facts(companies):
    _, paths, before, _ = merged(companies)
    after = copy.deepcopy(before)
    after.records.reverse()
    for record in after.records:
        record["id"] += "-new"
        for field in record["fields"].values():
            field["primary"] = None  # saved computed views are not authority
            field["candidates"].reverse()
            for fact in field["candidates"]:
                fact["id"] += "-new"
                fact["evidence"].reverse()
    assert stability(before, after)["records"]["rate"] == 1
    after.records[0]["fields"]["amount"]["candidates"][0]["value"] = 999
    result = stability(before, after)
    assert result["records"] == {"identical": 1, "total": 2, "rate": .5}
    assert result["fields"] == {"identical": 3, "total": 4, "rate": .75}
    assert result["changed_fields"][0]["field"] == "amount"
    assert "Garden" not in json.dumps(result) and "999" not in json.dumps(result)
    # Reading the real saved directories compares the same snapshot, without rewriting inputs.
    assert stability(load_run(paths[0]), load_run(paths[0].parent / "b"))["fields"]["rate"] == 1


@pytest.mark.parametrize("change", ["evidence", "review", "primary_language", "conflict", "i18n"])
def test_field_stability_preserves_evidence_language_conflict_review(companies, change):
    _, _, before, _ = merged(companies)
    after = copy.deepcopy(before)
    field = after.records[0]["fields"]["amount"]
    fact = field["candidates"][0]
    if change == "evidence":
        fact["evidence"][0]["locator"] = "§2"
    elif change == "review":
        fact["review_state"] = "proposed"
    elif change == "primary_language":
        field["primary_lang"] = "tr"
    else:
        other = copy.deepcopy(fact)
        other["value"] = 25
        if change == "i18n":
            other["lang"] = "tr"
        field["candidates"].append(other)
    assert stability(before, after)["fields"]["rate"] == .75


def test_missing_added_duplicate_records_and_empty_denominators(companies):
    _, _, before, _ = merged(companies)
    after = copy.deepcopy(before)
    after.records.pop()
    assert stability(before, after)["records"] == {"identical": 1, "total": 2, "rate": .5}
    after = copy.deepcopy(before)
    after.records.append(copy.deepcopy(after.records[0]))
    result = stability(before, after)
    assert result["records"] == {"identical": 2, "total": 3, "rate": 2 / 3}
    assert result["fields"] == {"identical": 4, "total": 6, "rate": 2 / 3}
    after.records = []
    before.records = []
    assert stability(before, after)["records"]["rate"] is None
    assert support(before, {})["unsupported_field_rate"] is None
    assert support(before, {})["target_met"] is False


@pytest.mark.parametrize("change", ["workspace", "version", "revision", "hash", "schema", "mode"])
def test_different_inputs_cannot_claim_stability(companies, change):
    _, _, before, _ = merged(companies)
    after = copy.deepcopy(before)
    if change == "workspace":
        after.workspace = "other"
    elif change == "schema":
        after.schema["version"] = 2
    elif change == "mode":
        after.mode = "extraction"
    else:
        key = {"version": "source_version_id", "revision": "knowledge_revision_id",
               "hash": "content_sha256"}[change]
        after.pins[0][key] = "changed"
    with pytest.raises(ValueError):
        stability(before, after)


def test_extraction_runs_keep_primary_i18n_conflicts_and_contexts(companies):
    _, paths = companies
    a = load_run(paths[0] / "sources")
    b = load_run(paths[0].parent / "b" / "sources")
    result = stability(a, b)
    assert result["input_verification"] == "pins_and_contexts"
    assert result["fields"]["rate"] == 1
    b.records[0]["fields"]["amount"]["i18n"]["tr"] = copy.deepcopy(
        b.records[0]["fields"]["amount"]["primary"])
    assert stability(a, b)["fields"]["rate"] == .75
    b.context_hashes["doc_1"] = "changed"
    with pytest.raises(ValueError, match="contexts"):
        stability(a, b)


@pytest.mark.parametrize("change,reason", [
    ("quote", "quote_not_found"), ("locator", "locator_not_found"),
    ("version", "evidence_pin_mismatch"), ("document", "document_not_pinned"),
    ("source_pin", "source_pin_mismatch"), ("missing", "source_missing"),
])
def test_support_validates_each_accepted_evidence(companies, change, reason):
    _, _, run, sources = merged(companies)
    evidence = run.records[0]["fields"]["amount"]["candidates"][0]["evidence"][0]
    if change == "quote":
        evidence["quote"] = "SOURCE_ONLY_SENTINEL"
    elif change == "locator":
        evidence["locator"] = "§99"
    elif change == "version":
        evidence["source_version_id"] = "wrong"
    elif change == "document":
        evidence["document_id"] = "other"
    elif change == "source_pin":
        sources["doc_1"][0]["content_sha256"] = "b" * 64
    else:
        sources.clear()
    report = support(run, sources)
    assert report["unsupported_fields"] >= 1
    assert reason in report["failure_reasons"]
    assert report["target_met"] is False
    assert "SOURCE_ONLY_SENTINEL" not in json.dumps(report)


def test_support_counts_accepted_languages_once_not_derived_views(companies):
    _, _, run, sources = merged(companies)
    field = run.records[0]["fields"]["amount"]
    field["candidates"][0]["review_state"] = "needs_review"
    rejected = copy.deepcopy(field["candidates"][0])
    rejected["review_state"] = "rejected"
    rejected["evidence"][0]["quote"] = "invented"
    field["candidates"].append(rejected)
    assert support(run, sources)["published_fields"] == 3
    assert support(run, sources)["unsupported_fields"] == 0
    translated = copy.deepcopy(run.records[1]["fields"]["name"]["candidates"][0])
    translated["lang"] = "tr"
    run.records[1]["fields"]["name"]["candidates"].append(translated)
    assert support(run, sources)["published_fields"] == 4
    # One bad citation fails a field even when another citation is valid.
    translated["evidence"].append({**translated["evidence"][0], "quote": "invented"})
    assert support(run, sources)["unsupported_fields"] == 1


def test_quote_must_be_in_the_pinned_block_not_another_block_or_footer(companies):
    _, paths, run, _ = merged(companies)
    context_path = paths[0] / "sources" / "doc_1" / "context.md"
    context_path.write_text("[§1 p.1]\nGarden\n[§2 p.2]\n20\n## Kaynak anahtarları\nRiver 30\n", encoding="utf-8")
    result = support(run, load_sources(paths[0] / "sources", run.workspace))
    assert result["published_fields"] == 4
    assert result["unsupported_fields"] == 3


def test_coverage_denominator_includes_omissions_and_ambiguous_rows(companies):
    _, paths, run, sources = merged(companies)
    run.records.pop()
    assert coverage(run, sources)["source_rows"] == 2
    assert coverage(run, sources)["covered_rows"] == 1
    context_path = paths[0] / "sources" / "doc_1" / "context.md"
    context_path.write_text("[§1 p.1]\n| Name | Amount |\n| --- | --- |\n"
                            "| Garden | 20 |\n| Garden | 25 |\n| 12 | 20 |\n"
                            "[§2 p.2]\n- Garden\n- Missing\n", encoding="utf-8")
    sources = load_sources(paths[0] / "sources", run.workspace)
    result = coverage(run, sources)
    assert result["source_rows"] == 5
    assert result["ambiguous_rows"] == 3
    assert result["covered_rows"] == 0  # Garden quote points to §1, not §2
    assert coverage(run, {})["rate"] is None


def test_duplicate_names_conflicts_and_empty_collections_remain_visible(companies):
    _, _, run, _ = merged(companies)
    assert normalized_name("King Suite") == normalized_name("King Suit Oda")
    for record, name in zip(run.records, ("King Suite", "King Suit Oda"), strict=True):
        record["fields"]["name"]["candidates"][0]["value"] = name
    field = run.records[0]["fields"]["amount"]
    other = copy.deepcopy(field["candidates"][0])
    other["value"] += 1
    other["review_state"] = "needs_review"
    field["candidates"].append(other)
    run.collections["empty"] = "empty"
    result = company_summary(run)
    assert len(result["possible_duplicates"]) == 1
    rooms = next(c for c in result["collections"] if c["key"] == "rooms")
    assert rooms["conflicting_field_languages"] == 1
    assert next(c for c in result["collections"] if c["key"] == "empty")["records"] == 0
    assert "King" not in json.dumps(result)
    other["review_state"] = "rejected"
    assert next(c for c in company_summary(run)["collections"] if c["key"] == "rooms")[
        "conflicting_field_languages"] == 0


def test_coverage_resolves_canonical_object_locator(companies):
    _, paths, run, _ = merged(companies)
    context_path = paths[0] / "sources" / "doc_1" / "context.md"
    context = context_path.read_text(encoding="utf-8")
    context_path.write_text(context + "## Kaynak anahtarları\n§1 → table_1 · evidence_1\n", encoding="utf-8")
    for record in run.records:
        for field in record["fields"].values():
            for fact in field["candidates"]:
                for e in fact["evidence"]:
                    e["locator"] = "table_1"
    sources = load_sources(paths[0] / "sources", run.workspace)
    assert support(run, sources)["unsupported_fields"] == 0
    assert coverage(run, sources)["covered_rows"] == 2


def test_legacy_hospitality_extraction_and_bundle_omissions_are_measured(companies):
    root, _ = companies
    legacy = root / "legacy" / "sources" / "legacy_doc"
    fact = {"value": "Garden room", "lang": "en", "evidence": [
        {"document_id": "legacy_doc", "locator": "§1", "quote": "Garden room"}]}
    write_json(legacy / "source.json", {
        "workspace_id": "legacy", "document_id": "legacy_doc", "source_version_id": "v1",
        "knowledge_revision_id": "k1", "content_sha256": "a" * 64, "lang": "en"})
    write_json(legacy / "records.json", {"document_id": "legacy_doc", "lang": "en",
               "records": [{"id": "1", "type": "room_type", "name": fact}]})
    (legacy / "context.md").write_text("[§1 p.1]\n- Garden room\n", encoding="utf-8")
    run = load_run(root / "legacy")
    assert run.collections["room_type"] == "rooms"
    assert coverage(run, load_sources(root / "legacy", "legacy"))["rate"] == 1
    write_json(root / "legacy_bundle.json", {"workspace_id": "legacy", "files": [
        {"document_id": "legacy_doc", "status": "done", "issues": []},
        {"document_id": "missing_doc", "status": "partial", "issues": [{"reason": "SOURCE_ONLY_SENTINEL"}]}]})
    assert main(["companies", "--workspaces", str(root / "legacy"), "--bundles",
                 str(root / "legacy_bundle.json"), "--out", str(root / "legacy.md")]) == 0
    result = json.loads((root / "legacy.json").read_text(encoding="utf-8"))["companies"][0]
    assert result["bundle"]["documents_missing_from_run"] == 1
    assert result["bundle"]["issue_count"] == 1
    assert "SOURCE_ONLY_SENTINEL" not in (root / "legacy.md").read_text(encoding="utf-8")


def test_invalid_duplicate_approval_rejected_by_publication_gate(companies, capsys):
    root, paths = companies
    revision_path = paths[0] / "merge" / "merge_revision.json"
    raw = json.loads(revision_path.read_text(encoding="utf-8"))
    candidates = raw["records"][0]["fields"]["amount"]["candidates"]
    extra = copy.deepcopy(candidates[0])
    extra["id"] = "extra"
    extra["value"] = 99
    candidates.append(extra)
    write_json(root / "invalid_revision.json", raw)
    assert main(["support", "--revision", str(root / "invalid_revision.json"),
                 "--sources", str(paths[0] / "sources")]) == 1
    assert "Garden" not in capsys.readouterr().err


def test_cli_rejects_ambiguous_or_invalid_inputs_without_printing_source(companies, capsys):
    root, paths = companies
    output = root / "bad"
    assert main(["stability", "--runs", str(paths[0].parent), str(paths[0]), "--out", str(output)]) == 1
    assert not output.exists()
    assert main(["companies", "--workspaces", str(paths[0]), str(paths[0]),
                 "--out", str(root / "duplicate.md")]) == 1
    source = paths[0] / "sources" / "doc_1" / "source.json"
    write_json(source, {"document_id": "SOURCE_ONLY_SENTINEL"})
    assert main(["support", "--revision", str(paths[0] / "merge" / "merge_revision.json"),
                 "--sources", str(paths[0] / "sources")]) == 1
    assert "SOURCE_ONLY_SENTINEL" not in capsys.readouterr().err
