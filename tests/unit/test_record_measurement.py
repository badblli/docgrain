"""Neutral scorer views retain missing display values and source identity."""

from docgrain_records.match import propose_matches, source_identity
from docgrain_records.match_merge import merge_matches, write_json
from docgrain_records.measurement import (
    extraction_scoring_records,
    merged_alignment_records,
    merged_scoring_views,
)
from docgrain_records.merge import JsonMergeStore, _json
from docgrain_records.models import ExtractionResult, RoomType


def test_measurement_views_do_not_resolve_conflicts_or_invent_english(tmp_path):
    def result(doc, lang, name, capacity):
        def fact(value):
            return {"value": value, "lang": lang, "evidence": [{
                "document_id": doc, "locator": "§1 p.1", "quote": str(value),
            }]}
        return ExtractionResult(document_id=doc, lang=lang, records=[RoomType(
            id=doc + ":1", name=fact(name), capacity=fact(capacity),
        )])

    results = [result("doc_en", "en", "Garden room", 2),
               result("doc_tr", "tr", "Garden room", 3)]
    for extracted in results:
        root = tmp_path / "in" / extracted.document_id
        write_json(root / "records.json", extracted.model_dump(mode="json"))
        write_json(root / "source.json", {
            "document_id": extracted.document_id, "lang": extracted.lang,
            "workspace_id": "workspace", "source_version_id": "version-1",
            "knowledge_revision_id": "revision-1", "content_sha256": "a" * 64,
        })
        (root / "context.md").write_text("[§1 p.1]\nGarden room; 2; 3", encoding="utf-8")
    revision = merge_matches(tmp_path / "in", results, propose_matches(results), tmp_path / "out",
                             auto_accept="strong")
    languages = {r.document_id: r.lang for r in results}
    views = merged_scoring_views(revision, languages)
    assert len(views) == 2
    assert all(v["fields"]["capacity"]["lang"] == "en" for v in views)
    localized = merged_scoring_views(revision, languages, source_language=True)
    tr = next(v for v in localized if v["document_id"] == "doc_tr")
    assert tr["fields"]["capacity"]["value"] == 3
    assert tr["i18n"]["tr"]["capacity"]["value"] == 3
    assert set(tr["fields"]["capacity"]["evidence"][0]) == {"document_id", "locator", "quote"}
    state = JsonMergeStore(tmp_path / "out" / "merge_state.json", "workspace")._read()
    proxies = merged_alignment_records(views, results, state.identity_map)
    assert {p["fields"]["name"]["lang"] for p in proxies} == {"en", "tr"}
    # An unresolved same-language primary is absent; its alternatives stay visible.
    conflicting = revision.model_copy(deep=True)
    field = conflicting.records[0].fields["capacity"]
    field.candidates[1].lang = field.candidates[0].lang
    for c in field.candidates:
        c.review_state = "needs_review"
    conflict_views = merged_scoring_views(conflicting, languages)
    assert all("capacity" not in v["fields"] for v in conflict_views)
    assert all({c["value"] for c in v["conflicts"]["capacity"]["candidates"]} == {2, 3}
               for v in conflict_views)
    assert all(v["conflicts"]["capacity"]["review_state"] == "needs_review" for v in conflict_views)
    # Source identity proxies never inject a primary value into the scored views.
    assert merged_alignment_records(conflict_views, results, state.identity_map) == proxies
    key = _json(["source", "doc_tr", "room_type", source_identity(results[1].records[0])])
    assert state.identity_map[key] == [revision.records[0].id]


def test_extraction_conflict_adapter_keeps_primary_and_all_alternatives():
    def fact(value):
        return {"value": value, "lang": "en", "evidence": [{
            "document_id": "doc", "locator": "§1", "quote": str(value),
        }]}
    record = RoomType(id="doc:1", name=fact("Garden room"), capacity=fact(2),
                      conflicts={"capacity": [fact(3)]}, review_state="needs_review")
    result = ExtractionResult(document_id="doc", lang="en", records=[record])
    view = extraction_scoring_records(result)[0]
    assert view["fields"]["capacity"]["value"] == 2
    assert {c["value"] for c in view["conflicts"]["capacity"]["candidates"]} == {2, 3}
    assert view["conflicts"]["capacity"]["review_state"] == "needs_review"
