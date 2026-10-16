"""WP114: source structure controls identity and heading evidence, without a model."""

import json
import socket

import pytest
from docgrain_domain.canonical.ai_output import context_projection, project_ai
from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunk_set
from docgrain_domain.canonical.lifecycle import processing_revision_id
from docgrain_records.auto_accept import apply_review_rules
from docgrain_records.extractor import ExtractionRun, build_messages
from docgrain_records.match import (
    accept_strong_matches,
    propose_matches,
    source_identity,
)
from docgrain_records.match_merge import (
    apply_matches,
    load_merge_documents,
    merge_matches,
    write_json,
)
from docgrain_records.models import RECORD_MODELS
from docgrain_records.runtime import RuntimeRecords
from docgrain_records.structure_context import StructureIndex, pin_structure
from docgrain_records.verify import _coalesce_document_records, verify_response
from docgrain_worker.canonical_mapper import CanonicalMapper
from docgrain_worker.structural import StructuralItem

from tests.fixtures.lifecycle import mapped_snapshot


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("WP114 tests must not contact a network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def snapshot_context(items):
    _, result, source, spec = mapped_snapshot()
    result.items = [StructuralItem(kind, f"item-{i}", {"kind": "text_span", "start": i * 100,
                                                   "end": i * 100 + len(text)}, text=text, level=level)
                    for i, (kind, text, level) in enumerate(items)]
    snapshot = CanonicalMapper().map(result, source, processing=spec, revision_id=processing_revision_id(source.id, spec),
                                     created_at=source.recorded_at)
    output = project_ai(snapshot, derive_chunk_set(snapshot, ChunkingSpec()))
    context = pin_structure(context_projection(output), snapshot.model_dump(mode="json"))
    index = StructureIndex(context)
    return context, {body: key for key, body in index.bodies.items()}


def fact(value, locator, quote=None, doc="document-test", lang="tr"):
    return {"value": value, "lang": lang, "evidence": [{"document_id": doc,
            "locator": locator, "quote": str(value) if quote is None else quote}]}


def candidate(kind="room_type", **fields):
    return {"type": kind, **{key: [] for key in RECORD_MODELS[kind][1].model_fields}, **fields}


def verify(records, context, doc="document-test", projected=None, runtime=None):
    return verify_response(json.dumps({"records": records}, ensure_ascii=False), projected or context,
                           doc, "tr", source_context=context, runtime=runtime)


def save_result(root, result, context):
    directory = root / result.document_id
    write_json(directory / "records.json", result.model_dump(mode="json"))
    write_json(directory / "source.json", {"document_id": result.document_id, "workspace_id": "workspace-test",
               "source_version_id": "version-test", "knowledge_revision_id": "revision-structure",
               "content_sha256": "a" * 64, "lang": result.lang})
    (directory / "context.md").write_text(context, encoding="utf-8")


def floor_result(doc="document-test"):
    context, keys = snapshot_context([
        ("heading", "Alt Kat", 1), ("paragraph", "Hol; Alan: 13,27 m²", 1),
        ("paragraph", "Hol; Alan: 13,27 m²; Kapasite: 2 kişi", 1),
        ("heading", "Çatı Katı", 1), ("paragraph", "Hol; Alan: 16,83 m²", 1),
    ])
    records = []
    for body, size in [("Hol; Alan: 13,27 m²", 13.27),
                       ("Hol; Alan: 13,27 m²; Kapasite: 2 kişi", 13.27),
                       ("Hol; Alan: 16,83 m²", 16.83)]:
        records.append(candidate(name=[fact("Hol", keys[body], doc=doc)],
                                 size_m2=[fact(size, keys[body], body, doc=doc)]))
    return context, verify(records, context, doc)


def test_floor_snapshot_separates_floors_and_merges_same_heading(tmp_path):
    context, result = floor_result()
    assert len(result.records) == 2 and not result.rejected
    assert not any(record.conflicts for record in result.records)
    assert {r.structure_context[0].section_title for r in result.records} == {"Alt Kat", "Çatı Katı"}
    assert len(result.records[0].name.evidence) == 2
    assert len({source_identity(r) for r in result.records}) == 2
    save_result(tmp_path / "records", result, context)
    revision = merge_matches(tmp_path / "records", [result], propose_matches([result]), tmp_path / "out")
    approved, _ = apply_review_rules(revision)
    assert len(approved.records) == 2
    assert all(field.primary is not None and field.primary.review_state == "accepted"
               for record in approved.records for field in record.fields.values())


def test_missing_context_does_not_bridge_distinct_floors():
    _, result = floor_result()
    sparse = result.records[0].model_copy(deep=True)
    sparse.structure_context = []
    for e in sparse.name.evidence:
        e.structure_context = None
    assert len(_coalesce_document_records([sparse, *result.records], "tr")) == 3
    assert len(_coalesce_document_records([sparse, result.records[0]], "tr")) == 1


def test_cross_document_strong_names_and_transitive_bridge_cannot_bypass_structure(tmp_path):
    context, first = floor_result()
    _, other = floor_result("doc-other")
    proposals = accept_strong_matches([first, other], propose_matches([first, other], strong_names=True))

    def floor(ref):
        return "Çatı Katı" if "çatı katı" in ref.source_identity else "Alt Kat"

    assert len(proposals.proposals) == 4
    for p in proposals.proposals:
        if floor(p.left) == floor(p.right):
            assert p.decision == "same" and p.review_state == "accepted"
        else:
            assert p.decision == "different" and p.review_state == "proposed"
            assert any(s.kind == "structure_conflict" for s in p.signals)
    save_result(tmp_path / "records", first, context)
    save_result(tmp_path / "records", other, context)
    revision = merge_matches(tmp_path / "records", [first, other], proposals, tmp_path / "out")
    assert len(revision.records) == 2
    forged = proposals.model_copy(deep=True)
    forged.proposals = [p for p in forged.proposals if floor(p.left) != floor(p.right)][:1]
    p = forged.proposals[0]
    p.decision, p.review_state, p.reviewer, p.reason = "same", "accepted", "reviewer", "Checked"
    documents = load_merge_documents(tmp_path / "records", [first, other])
    with pytest.raises(ValueError, match="conflicting pair"):
        apply_matches(documents, forged)
    sparse = verify([candidate(name=[fact("Hol", "§1", doc="doc-sparse")])],
                    "[§1 p.1]\nHol", "doc-sparse")
    bridged = accept_strong_matches([first, sparse, other], propose_matches([first, sparse, other]))
    assert not any(p.review_state == "accepted" and "doc-sparse" in {p.left.document_id, p.right.document_id}
                   for p in bridged.proposals)


def test_cross_document_headings_with_different_vocabularies_still_merge(tmp_path):
    """A brochure's "Odalar" and a price list's "2026 Fiyatları" are not competing locations."""
    brochure, brochure_keys = snapshot_context([("heading", "Odalar", 1), ("paragraph", "Garden Room; 32 m²", 1)])
    prices, price_keys = snapshot_context([("heading", "2026 Fiyatları", 1), ("paragraph", "Garden Room; 32 m²", 1)])
    results = []
    for doc, context, keys in [("doc-brochure", brochure, brochure_keys), ("doc-prices", prices, price_keys)]:
        key = keys["Garden Room; 32 m²"]
        results.append(verify([candidate(name=[fact("Garden Room", key, doc=doc, lang="en")],
                                         size_m2=[fact(32, key, "Garden Room; 32 m²", doc=doc, lang="en")])],
                              context, doc))
        save_result(tmp_path / "records", results[-1], context)
    assert all(r.records[0].structure_context[0].section_title for r in results)
    proposals = accept_strong_matches(results, propose_matches(results, strong_names=True))
    assert [p.review_state for p in proposals.proposals] == ["accepted"]
    assert not any(s.kind == "structure_conflict" for s in proposals.proposals[0].signals)
    revision = merge_matches(tmp_path / "records", results, proposals, tmp_path / "out")
    assert len(revision.records) == 1


@pytest.mark.parametrize("heading", ["Çorba", "Soup", "Suppe", "Суп"])
def test_menu_category_uses_its_containing_heading(heading, tmp_path):
    context, keys = snapshot_context([("heading", heading, 1), ("paragraph", "Bahçe Menüsü", 1)])
    runtime = RuntimeRecords({"workspace_id": "workspace-test", "version": 1, "review_state": "accepted",
        "sources": [], "collections": [{"key": "dishes", "label_i18n": [{"lang": "en", "value": "Dishes"}],
        "description": "Menu dishes", "review_state": "accepted", "identity": "name",
        "fields": [{"key": field, "type": "string", "unit": None, "review_state": "accepted",
                    "label_i18n": [{"lang": "en", "value": field}]} for field in ("name", "category")],
        "examples": [{"values": [{"key": "name", **fact("Bahçe Menüsü", keys["Bahçe Menüsü"])}]}]}]})
    record = {"type": "dishes", "name": [fact("Bahçe Menüsü", keys["Bahçe Menüsü"])],
              "category": [fact(heading, keys["# " + heading])]}
    result = verify([record], context, runtime=runtime)
    assert not result.rejected and result.records[0].category.value == heading
    evidence = result.records[0].category.evidence[0]
    assert evidence.locator == keys["# " + heading] and evidence.quote == heading
    save_result(tmp_path / "records", result, context)
    revision = merge_matches(tmp_path / "records", [result], propose_matches([result]), tmp_path / "out")
    approved, _ = apply_review_rules(revision)
    assert approved.records[0].fields["category"].primary.review_state == "accepted"


@pytest.mark.parametrize("wrong_heading", [False, True])
def test_bare_or_sibling_category_remains_rejected(wrong_heading):
    items = [("heading" if wrong_heading else "paragraph", "Çorba", 1),
             ("heading", "Tatlı", 1), ("paragraph", "Bahçe Menüsü", 1)]
    context, keys = snapshot_context(items)
    locator = keys["# Çorba" if wrong_heading else "Çorba"]
    result = verify([candidate("property", name=[fact("Bahçe Menüsü", keys["Bahçe Menüsü"])],
                               category=[fact("Çorba", locator)])], context)
    assert result.records[0].category is None
    assert result.rejected[0].reason == "bare_value_quote"


def test_containing_heading_survives_a_scan_section_without_the_heading():
    context, keys = snapshot_context([("heading", "Çorba", 1), ("paragraph", "Bahçe Menüsü", 1)])
    projected = f"[{keys['Bahçe Menüsü']} p.1]\nBahçe Menüsü\n"
    record = candidate("property", name=[fact("Bahçe Menüsü", keys["Bahçe Menüsü"])],
                       category=[fact("Çorba", keys["# Çorba"])])
    result = verify([record], context, projected=projected)
    assert not result.rejected and result.records[0].category.value == "Çorba"
    prompt = json.loads(build_messages(projected, "document-test", "tr", source_context=context)[1]["content"])
    assert prompt["untrusted_containing_headings"] == {keys["# Çorba"]: "Çorba"}


def test_table_headers_are_derived_not_taken_from_proposed_metadata():
    context = '[§1 p.1]\n# Alt Kat\n\n[§2 p.1]\n| Oda | Alan |\n| --- | --- |\n| Hol | 13 |\n'
    cell = '§2 cell={"row":1,"column":2,"column_header":"Alan"}'
    result = verify([candidate(name=[fact("Hol", '§2 cell={"row":1,"column":1,"row_header":"Hol"}')],
                               size_m2=[fact(13, cell)])], context)
    assert not result.rejected
    metadata = result.records[0].size_m2.evidence[0].structure_context
    assert (metadata.table_row, metadata.table_column, metadata.row_header, metadata.column_header) == (1, 2, "Hol", "Alan")


def test_table_record_context_uses_unique_fact_cells_for_repeated_names():
    context = '[§1 p.1]\n| Daire | Oda | Alan |\n| --- | --- | --- |\n| A | Hol | 13 |\n| B | Hol | 16 |\n'
    result = verify([candidate(name=[fact("Hol", "§1")], size_m2=[fact(size,
                     f'§1 cell={{"row":{row},"column":3,"column_header":"Alan"}}')])
                     for row, size in [(1, 13), (2, 16)]], context)
    assert len(result.records) == 2 and not result.rejected
    assert {c.row_header for r in result.records for c in r.structure_context if c.row_header} == {"A", "B"}


def test_proposed_structure_cannot_forge_heading_containment():
    context, keys = snapshot_context([("heading", "Alt Kat", 1), ("paragraph", "Hol", 1)])
    proposed = fact("Hol", keys["Hol"])
    proposed["evidence"][0]["structure_context"] = {"heading_path": [
        {"locator": "§999", "title": "Sahte Kat"}], "section_title": "Sahte Kat"}
    result = verify([candidate(name=[proposed])], context)
    assert result.records[0].name.evidence[0].structure_context.section_title == "Alt Kat"


def test_nested_units_with_equal_local_headings_remain_separate():
    context, keys = snapshot_context([
        ("heading", "A Blok", 1), ("heading", "Alt Kat", 2), ("paragraph", "Hol; Alan: 13 m²", 1),
        ("heading", "B Blok", 1), ("heading", "Alt Kat", 2), ("paragraph", "Hol; Alan: 16 m²", 1)])
    result = verify([candidate(name=[fact("Hol", keys[body])], size_m2=[fact(size, keys[body], body)])
                     for body, size in [("Hol; Alan: 13 m²", 13), ("Hol; Alan: 16 m²", 16)]], context)
    assert len(result.records) == 2
    assert {r.structure_context[0].heading_path[0].title for r in result.records} == {"A Blok", "B Blok"}


def test_grouped_pipeline_extraction_retains_source_context():
    context, result = floor_result()
    class Fake:
        def complete(self, messages, **kwargs):
            assert "untrusted_containing_headings" in json.loads(messages[1]["content"])
            return json.dumps({"records": []})
    run = ExtractionRun(context, result.document_id, result.lang, Fake(), grouped_passes=True)
    assert not run.run().result().failures


def test_consolidation_report_cli_detects_legacy_over_merge_and_under_merge(tmp_path, capsys):
    from benchmarks.consolidation_report import build_report, main

    context, result = floor_result()
    # Reproduce a pre-WP114 name-only merge without changing any source quotations.
    legacy = result.model_copy(deep=True)
    for r in legacy.records:
        r.structure_context = []
        for e in r.name.evidence:
            e.structure_context = None
    legacy.records = _coalesce_document_records(legacy.records, "tr")
    # The store now prevents it; construct the historical artifact from separate fields.
    save_result(tmp_path / "records", result, context)
    revision = merge_matches(tmp_path / "records", [result], propose_matches([result]), tmp_path / "out")
    a, b = revision.records
    a.fields["size_m2"].candidates.extend(b.fields["size_m2"].candidates)
    revision.records = [a]
    duplicate = a.model_copy(deep=True)
    duplicate.id = "record-similar"
    duplicate.fields["size_m2"].candidates = duplicate.fields["size_m2"].candidates[:1]
    revision.records.append(duplicate)
    path = tmp_path / "revision.json"
    write_json(path, revision.model_dump(mode="json", round_trip=True))
    assert main(["--workspace", "workspace-test", "--revision", str(path), "--records",
                 str(tmp_path / "records"), "--out", str(tmp_path / "report")]) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["suspected_over_merges"] and report["suspected_under_merges"]
    assert {s["reason"] for s in report["suspected_over_merges"]} == {"different_structure"}
    assert len(report["conflicts"]["real"]) == 1 and report["unsupported_fields"] == 0
    assert "Fazla birleştirme şüphesi" in (tmp_path / "report.md").read_text(encoding="utf-8")
    # A real value mismatch in the cited quote is unsupported, even with nonempty evidence.
    revision.records[0].fields["size_m2"].candidates[0].value = 999
    broken = build_report(revision, [result], {result.document_id: context})
    assert broken["unsupported_fields"] > 0
    assert "Hol" not in capsys.readouterr().out


def menu_runtime(keys, category_key="category"):
    return RuntimeRecords({"workspace_id": "workspace-test", "version": 1, "review_state": "accepted",
        "sources": [], "collections": [{"key": "dishes", "label_i18n": [{"lang": "en", "value": "Dishes"}],
        "description": "Menu dishes", "review_state": "accepted", "identity": "name",
        "fields": [{"key": field, "type": "string", "unit": None, "review_state": "accepted",
                    "label_i18n": [{"lang": "en", "value": field}]} for field in ("name", category_key)],
        "examples": [{"values": [{"key": "name", **fact("Mercimek", keys["Mercimek"])}]}]}]})


def test_bilingual_heading_segments_are_heading_evidence_per_language():
    context, keys = snapshot_context([("heading", "Çorba / Soup", 1), ("paragraph", "Mercimek", 1)])
    heading = keys["# Çorba / Soup"]
    record = {"type": "dishes", "name": [fact("Mercimek", keys["Mercimek"])],
              "category": [fact("Soup", heading, lang="en"), fact("Çorba", heading)]}
    result = verify([record], context, runtime=menu_runtime(keys))
    assert not result.rejected
    assert result.records[0].category.value == "Soup"
    assert result.records[0].i18n["tr"].category.value == "Çorba"
    # The containing heading's segment is the evidence itself (not a widened WP102 label).
    assert [e.quote for e in result.records[0].category.evidence] == ["Soup"]
    assert result.records[0].category.evidence[0].locator == heading
    # Only whole separated segments count: a fragment of one word is not the heading.
    fragment = {"type": "dishes", "name": [fact("Mercimek", keys["Mercimek"])],
                "category": [fact("orba", heading)]}
    assert verify([fragment], context, runtime=menu_runtime(keys)).records[0].category is None


def test_heading_field_names_cover_suffixed_keys():
    from docgrain_records.verify import _heading_field

    assert all(map(_heading_field, ["category", "dish_category", "room_type", "floor", "menu_section"]))
    assert not any(map(_heading_field, ["price", "name", "categoryless", "status"]))


def test_structure_lines_stay_out_of_prompts_and_section_sizes():
    from docgrain_records.extractor import extraction_plan
    from docgrain_records.structure_context import without_structure

    context, _ = floor_result()
    assert "structure=" in context and "structure=" not in without_structure(context)
    assert StructureIndex(without_structure(context)).bodies == StructureIndex(context).bodies
    prompt = build_messages(context, "document-test", "tr", source_context=context)[1]["content"]
    assert "structure=" not in json.loads(prompt)["untrusted_source_context"]
    assert all("structure=" not in section.context for section, _ in extraction_plan(context))
    assert ([s.source_keys for s, _ in extraction_plan(context)]
            == [s.source_keys for s, _ in extraction_plan(without_structure(context))])


def test_report_flags_unstructured_same_document_conflicts(tmp_path):
    from benchmarks.consolidation_report import build_report

    # Drawing labels without headings: no structure separates the two "Hol" blocks.
    context = "[§1 p.1]\nHol; Alan: 13,27 m²\n\n[§2 p.1]\nHol; Alan: 16,83 m²\n"
    result = verify([candidate(name=[fact("Hol", key)], size_m2=[fact(size, key, body)])
                     for key, body, size in [("§1", "Hol; Alan: 13,27 m²", 13.27),
                                             ("§2", "Hol; Alan: 16,83 m²", 16.83)]], context)
    assert len(result.records) == 1 and result.records[0].conflicts
    save_result(tmp_path / "records", result, context)
    revision = merge_matches(tmp_path / "records", [result], propose_matches([result]), tmp_path / "out")
    report = build_report(revision, [result], {result.document_id: context})
    assert [s["reason"] for s in report["suspected_over_merges"]] == ["same_document_different_blocks"]
    assert report["unsupported_fields"] == 0


def test_report_lists_same_name_split_by_sections_but_not_distinct_floors(tmp_path):
    from benchmarks.consolidation_report import build_report

    context, keys = snapshot_context([
        ("heading", "Odalar", 1), ("paragraph", "Garden Room; 32 m²", 1),
        ("heading", "Kapasite", 1), ("paragraph", "Garden Room; Kapasite: 2 kişi", 1)])
    first, second = keys["Garden Room; 32 m²"], keys["Garden Room; Kapasite: 2 kişi"]
    result = verify([candidate(name=[fact("Garden Room", first, lang="en")],
                               size_m2=[fact(32, first, "Garden Room; 32 m²", lang="en")]),
                     candidate(name=[fact("Garden Room", second, lang="en")],
                               capacity=[fact(2, second, "Kapasite: 2 kişi")])], context)
    assert len(result.records) == 2  # WP114: different sections of one document stay separate
    save_result(tmp_path / "records", result, context)
    revision = merge_matches(tmp_path / "records", [result], propose_matches([result]), tmp_path / "out")
    report = build_report(revision, [result], {result.document_id: context})
    assert [s["reason"] for s in report["suspected_under_merges"]] == ["same_name_different_structure"]

    floor_context, floors = floor_result()
    save_result(tmp_path / "floors", floors, floor_context)
    revision = merge_matches(tmp_path / "floors", [floors], propose_matches([floors]), tmp_path / "out2")
    report = build_report(revision, [floors], {floors.document_id: floor_context})
    assert report["suspected_under_merges"] == [] and report["suspected_over_merges"] == []
