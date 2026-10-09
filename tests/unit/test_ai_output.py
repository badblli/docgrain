import json
from hashlib import sha256

import jsonschema
import pytest
from docgrain_domain.canonical.ai_output import output_bundle
from docgrain_domain.source_format import IMAGE_FORMATS, SourceFormat

from tests.fixtures.lifecycle import mapped_snapshot
from tests.unit.test_m2c_chunking import rich_snapshot


@pytest.mark.parametrize("fmt", list(SourceFormat))
def test_single_consumer_schema_and_source_evidence_preserved(fmt):
    snapshot, _, _, _ = mapped_snapshot(fmt)
    output, chunks, revision, files = output_bundle(snapshot)
    jsonschema.Draft202012Validator(json.loads(files["ai.schema.json"])).validate(json.loads(files["ai.json"]))
    assert output.version == ("1.1.0" if fmt in IMAGE_FORMATS else "1.0.0")
    assert output.source == snapshot.source_version
    assert {n.id:n.model_dump(mode="json") for n in output.content} == {
        n.id:n.model_dump(mode="json") for n in snapshot.structure}
    assert output.evidence == snapshot.evidence
    assert json.loads(files["canonical.json"]) == snapshot.model_dump(mode="json")
    assert chunks.revision.processing_revision_id == revision.processing_revision_id == snapshot.knowledge_revision.id
    assert output.quality.semantic_status in {"not_assessed", "needs_enrichment"}  # no semantic success state
    manifest = json.loads(files["manifest.json"])
    for item in manifest["files"]:
        assert sha256(files[item["name"]]).hexdigest() == item["sha256"]
    assert output_bundle(snapshot)[3] == files


def test_table_values_formula_spans_and_visual_gaps_are_not_flattened():
    snapshot = rich_snapshot()
    output, _, _, files = output_bundle(snapshot)
    before = [n.model_dump(mode="json")["rows"] for n in snapshot.structure if n.kind == "table"]
    after = [n.model_dump(mode="json")["rows"] for n in output.content if n.kind == "table"]
    assert before == after
    assert output.quality.source_to_parser == "not_independently_verified"
    assert output.quality.semantic_status == "needs_enrichment"
    assert not output.quality.text_only_complete
    assert "missing_visual_description" in {g.code for g in output.quality.gaps}
    assert "requires image interpretation" in files["canonical.md"].decode()


def test_partial_and_empty_text_are_explicit_negative_acceptance():
    snapshot,_,_,_ = mapped_snapshot()
    value = snapshot.model_dump(mode="json")
    value["structure"][-1]["text"] = ""
    value["metadata"] = {"structural_parse":{"coverage":{"status":"partial"},"issues":[{"code":"needs_ocr"}]}}
    from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
    output, _, _, _ = output_bundle(CanonicalKnowledgeSnapshot.model_validate(value))
    assert not output.quality.text_only_complete
    assert {g.code for g in output.quality.gaps} >= {"parser_issue","no_text_or_table_content","structural_coverage_incomplete"}


def test_postgresql_json_key_reordering_cannot_change_output_checksums():
    snapshot,*_ = mapped_snapshot()
    value = snapshot.model_dump(mode="json")
    value["metadata"] = {"structural_parse":{"coverage":{"status":"partial"},
        "issues":[{"stage":"structural_parse","code":"review","reason":"Example issue"}]}}
    from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
    first = CanonicalKnowledgeSnapshot.model_validate(value)
    replay = CanonicalKnowledgeSnapshot.model_validate(json.loads(json.dumps(value,sort_keys=True)))
    assert output_bundle(first)[3] == output_bundle(replay)[3]
