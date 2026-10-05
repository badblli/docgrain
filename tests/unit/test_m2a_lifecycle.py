"""Executable M2a design spikes, independent of providers and external services."""

import copy
import json
from pathlib import Path

import pymupdf
import pytest
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, canonical_json_bytes
from docgrain_domain.canonical.lifecycle import (
    DerivedRevision,
    ProcessingSpec,
    chunk_id,
    entity_id,
    logical_document_id,
    processing_revision_id,
    source_revision_id,
)
from docgrain_domain.canonical.lineage import DerivedManifest, LineageGraph, ObjectRef
from docgrain_domain.canonical.schema import (
    generated_core_schema_text,
    generated_lineage_schema_text,
)
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.canonical_mapper import CanonicalMapper

from tests.fixtures.lifecycle import derived_chain, mapped_snapshot


def test_source_and_processing_boundaries():
    source = source_revision_id("workspace", "document", "a" * 64)
    first = ProcessingSpec(parser="parser", parser_version="1", options={"ocr": False})
    replay = ProcessingSpec(parser="parser", parser_version="1", options={"ocr": False})
    changed = ProcessingSpec(parser="parser", parser_version="1", options={"ocr": True})
    assert first.digest == replay.digest
    assert processing_revision_id(source, first) == processing_revision_id(source, replay)
    assert processing_revision_id(source, first) != processing_revision_id(source, changed)
    assert source == source_revision_id("workspace", "document", "a" * 64)
    assert source != source_revision_id("other", "document", "a" * 64)
    assert source != source_revision_id("workspace", "other", "a" * 64)


def test_config_order_and_all_identity_boundaries():
    first = ProcessingSpec(parser="p", parser_version="1", options={"a": True, "b": 2})
    assert first.digest == ProcessingSpec(parser="p", parser_version="1", options={"b": 2, "a": True}).digest
    for change in ({"parser_version": "2"}, {"dependencies": {"dependency": "2"}},
                   {"mapper_version": "2"}, {"options": {"a": False, "b": 2}}):
        assert ProcessingSpec.model_validate({**first.model_dump(), **change}).digest != first.digest
    assert logical_document_id("w", "connector", "key") != logical_document_id("w2", "connector", "key")
    assert entity_id("d", "schema1", "key") != entity_id("d", "schema2", "key")
    assert chunk_id("d", ["a", "b"], "split", "1", 0, "a" * 64) != chunk_id(
        "d", ["b", "a"], "split", "1", 0, "a" * 64)
    with pytest.raises(ValueError):
        source_revision_id("w", "d", "invalid")


@pytest.mark.parametrize("fmt", list(SourceFormat))
def test_reparse_preserves_identity_and_config_changes_only_processing(tmp_path, fmt):
    pdf_path = tmp_path / "frame.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=600, height=800)
        pdf.save(pdf_path)
    first, result, source, spec = mapped_snapshot(fmt, pdf_path=pdf_path)
    replay, *_ = mapped_snapshot(fmt, pdf_path=pdf_path)
    assert canonical_json_bytes(first.model_dump(mode="json")) == canonical_json_bytes(replay.model_dump(mode="json"))
    changed, *_ = mapped_snapshot(fmt, pdf_path=pdf_path, mapper_version="m2a-2")
    assert first.source_version == changed.source_version
    assert first.knowledge_revision.id != changed.knowledge_revision.id
    assert [n.id for n in first.structure] == [n.id for n in changed.structure]
    result.items[0].text = "Content correction at the same source anchor"
    corrected = CanonicalMapper().map(result, source, processing=spec,
                                     revision_id=first.knowledge_revision.id, created_at=source.recorded_at,
                                     pdf_path=pdf_path)
    assert corrected.structure[-1].id == first.structure[-1].id
    # A conflicting payload with the same revision identity must be rejected at publication.
    assert corrected.structure[-1].text != first.structure[-1].text
    graph = LineageGraph(first)
    canonical, manifests = derived_chain(first)
    for manifest in manifests:
        graph.extend(manifest)
    forward = graph.trace(canonical, "downstream")
    assert {obj.kind for obj in forward.objects} == {"canonical", "chunk", "embedding", "index"}
    backward = graph.trace(manifests[-1].objects[0], "upstream")
    assert {obj.kind for obj in backward.objects} == {"source", "processing", "canonical", "chunk", "embedding", "index"}
    assert next(obj for obj in backward.objects if obj.kind == "source").revision_id == source.id


def test_lineage_rejects_unknown_occurrences_cross_revision_scope_and_limits():
    snapshot, *_ = mapped_snapshot()
    canonical, manifests = derived_chain(snapshot)
    graph = LineageGraph(snapshot)
    with pytest.raises(ValueError, match="unknown upstream"):
        graph.extend(manifests[1])
    for manifest in manifests:
        graph.extend(manifest)
    with pytest.raises(ValueError, match="already registered"):
        graph.extend(manifests[0])
    with pytest.raises(KeyError):
        graph.trace(ObjectRef(kind="canonical", object_id=canonical.object_id, revision_id="other"), "downstream")
    with pytest.raises(ValueError, match="max_objects"):
        graph.trace(canonical, "downstream", max_objects=2)
    bounded = graph.trace(canonical, "downstream", max_depth=1)
    assert len(bounded.objects) == 2 and bounded.depth_limited
    wrong = manifests[0].model_dump(mode="json")
    wrong["revision"]["workspace_id"] = "other"
    with pytest.raises(ValueError, match="derived revision ID"):
        DerivedManifest.model_validate(wrong)
    changed_revision = DerivedRevision.create(**{
        **manifests[0].revision.model_dump(exclude={"id"}), "workspace_id": "other"})
    wrong["revision"] = changed_revision.model_dump(mode="json")
    wrong["objects"][0]["revision_id"] = changed_revision.id
    wrong["edges"][0]["downstream"]["revision_id"] = changed_revision.id
    with pytest.raises(ValueError, match="scope mismatch"):
        LineageGraph(snapshot).extend(DerivedManifest.model_validate(wrong))


def test_new_schema_and_historical_contracts():
    from jsonschema import Draft202012Validator

    schemas = Path(__file__).resolve().parents[2] / "packages/domain/docgrain_domain/canonical/schemas"
    text = (schemas / "canonical-knowledge-0.3.0.schema.json").read_text(encoding="utf-8")
    assert text == generated_core_schema_text("0.3.0")
    validator = Draft202012Validator(json.loads(text))
    snapshot, *_ = mapped_snapshot()
    validator.validate(snapshot.model_dump(mode="json"))
    fixture = Path(__file__).resolve().parents[1] / "fixtures/canonical/generic-pdf.json"
    historical = json.loads(fixture.read_text(encoding="utf-8"))
    historical["schema_version"] = "0.2.0"
    old_snapshot = CanonicalKnowledgeSnapshot.model_validate(historical)
    assert "processing" not in old_snapshot.model_dump(mode="json")["knowledge_revision"]
    Draft202012Validator(json.loads((schemas / "canonical-knowledge-0.2.0.schema.json").read_text(
        encoding="utf-8"))).validate(old_snapshot.model_dump(mode="json"))
    manifest_text = (schemas / "derived-manifest-0.1.0.schema.json").read_text(encoding="utf-8")
    assert manifest_text == generated_lineage_schema_text()
    _, manifests = derived_chain(snapshot)
    Draft202012Validator(json.loads(manifest_text)).validate(manifests[0].model_dump(mode="json"))
    value = snapshot.model_dump(mode="json")
    for mutate in (lambda v: v["source_version"].update(id="wrong"),
                   lambda v: v["knowledge_revision"]["processing"].update(mapper_version="wrong"),
                   lambda v: v["structure"][0].update(id="wrong")):
        invalid = copy.deepcopy(value)
        mutate(invalid)
        with pytest.raises(ValueError):
            CanonicalKnowledgeSnapshot.model_validate(invalid)
