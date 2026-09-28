"""M1 canonical contract and generated-schema tests (no parser or provider calls)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from docgrain_domain.canonical import (
    CanonicalKnowledgeSnapshot,
    DateRange,
    DatetimeRange,
    DocxBlockLocator,
    NormalizedBox,
    PdfPageLocator,
    SpreadsheetRangeLocator,
    TextSpanLocator,
    canonical_export_path,
    canonical_json_bytes,
    deterministic_item_id,
)
from docgrain_domain.canonical.domain_validation import validate_domain_record
from docgrain_domain.canonical.schema import generated_core_schema_text
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "canonical"
SCHEMA = Path(__file__).resolve().parents[2] / "packages" / "domain" / "docgrain_domain" / "canonical" / "schemas" / "canonical-knowledge-0.1.0.schema.json"


def fixture(name: str = "generic-pdf.json") -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def rejected(mutator, message: str, name: str = "generic-pdf.json") -> None:
    value = copy.deepcopy(fixture(name))
    mutator(value)
    with pytest.raises(ValidationError, match=message):
        CanonicalKnowledgeSnapshot.model_validate(value)


def test_valid_snapshot_and_unicode_null_round_trip() -> None:
    value = CanonicalKnowledgeSnapshot.model_validate(fixture())
    data = json.loads(canonical_json_bytes(value.model_dump(mode="json")))
    assert data["structure"][2]["text"].startswith("İzmir")
    assert data["structure"][2]["annotation"]["provenance"]["confidence"] is None
    assert CanonicalKnowledgeSnapshot.model_validate(data) == value
    assert canonical_export_path("doc", "rev") == "documents/doc/knowledge/rev/canonical.json"


def test_source_revision_and_producer_models_are_frozen() -> None:
    value = CanonicalKnowledgeSnapshot.model_validate(fixture())
    with pytest.raises(ValidationError, match="frozen_instance"):
        value.source_version.storage_uri = "fixture://changed"
    with pytest.raises(ValidationError, match="frozen_instance"):
        value.knowledge_revision.id = "changed"
    with pytest.raises(ValidationError, match="frozen_instance"):
        value.knowledge_revision.producers[0].name = "changed"


def test_review_status_is_distinct_from_provenance_and_confidence() -> None:
    rejected(lambda v: v["structure"][0]["annotation"].update(review_status="extracted"), "literal_error")
    rejected(lambda v: v["structure"][0]["annotation"]["provenance"].update(
        confidence=0.9), "confidence_method is required")


def test_unknown_core_field_and_non_json_metadata_rejected() -> None:
    rejected(lambda v: v.update(unknown_core="ignored"), "extra_forbidden")
    value = fixture()
    value["metadata"]["date"] = object()
    with pytest.raises(ValidationError):
        CanonicalKnowledgeSnapshot.model_validate(value)


def test_locators_and_bbox_bounds() -> None:
    PdfPageLocator(page_number=1, bbox=NormalizedBox(x=0.1, y=0.2, width=0.3, height=0.4))
    DocxBlockLocator(part="word/document.xml", path="/body/p[2]")
    assert SpreadsheetRangeLocator(sheet="Sheet1", a1_range="a2:b3").a1_range == "A2:B3"
    assert TextSpanLocator(start=0, end=2).end == 2
    with pytest.raises(ValidationError):
        NormalizedBox(x=0.8, y=0, width=0.3, height=0.1)
    with pytest.raises(ValidationError):
        TextSpanLocator(start=2, end=2)
    with pytest.raises(ValidationError):
        SpreadsheetRangeLocator(sheet="Sheet1", a1_range="B2:A1")
    rejected(lambda v: v["evidence"][0].update(locator={"kind": "unknown"}), "union_tag_invalid")


def test_temporal_half_open_and_timezone_rules() -> None:
    DateRange(valid_from="2026-01-01")
    DatetimeRange(valid_until="2026-01-01T00:00:00Z")
    for value in (
        {"kind": "date_range"},
        {"kind": "date_range", "valid_from": "2026-01-01", "valid_until": "2026-01-01"},
        {"kind": "datetime_range", "valid_from": "2026-01-01T00:00:00"},
        {"kind": "datetime_range", "valid_from": "2026-01-02T00:00:00Z",
         "valid_until": "2026-01-01T00:00:00Z"},
    ):
        rejected(lambda v, item=value: v["entities"][0].update(validity=item), "Value error")


@pytest.mark.parametrize("mutation,message", [
    (lambda v: v["structure"][1].update(id=v["structure"][0]["id"]), "duplicate"),
    (lambda v: v["structure"][0]["children"].append("missing"), "dangling child"),
    (lambda v: v["structure"][0]["annotation"]["provenance"]["evidence_ids"].append("missing"), "dangling evidence"),
    (lambda v: v["relations"][0].update(to_entity_id="missing"), "dangling relation"),
    (lambda v: v["structure"][1]["children"].append(v["structure"][0]["id"]), "root has a parent"),
    (lambda v: v["structure"][0]["children"].append(v["structure"][2]["id"]), "more than one parent"),
    (lambda v: v["entities"][0]["annotation"]["provenance"].update(producer_id="missing"), "dangling producer"),
    (lambda v: v["knowledge_revision"].update(source_version_id="other"), "source_version_id mismatch"),
    (lambda v: v["source_version"].update(workspace_id="other"), "scope mismatch"),
    (lambda v: v["knowledge_revision"].update(document_id="other"), "scope mismatch"),
    (lambda v: v["evidence"][0].update(source_version_id="other"), "evidence source mismatch"),
    (lambda v: v["structure"][0].update(id=v["entities"][0]["id"]), "duplicate"),
    (lambda v: v["records"][0].update(schema_id="missing"), "dangling domain schema"),
    (lambda v: v["records"][0].update(entity_ids=["missing"]), "dangling domain record entity"),
])
def test_semantic_rejections(mutation, message: str) -> None:
    fixture_name = "domain-example.json" if "domain" in message else "generic-pdf.json"
    rejected(mutation, message, fixture_name)


def test_structural_cycle_below_root() -> None:
    def cycle(value: dict) -> None:
        section = value["structure"][1]
        paragraph = value["structure"][2]
        paragraph["kind"] = "list"
        paragraph.pop("text")
        paragraph.pop("role")
        paragraph["children"] = [section["id"]]
    rejected(cycle, "structural cycle|root has a parent|more than one parent")


def test_identity_policy_is_deterministic_and_revision_independent() -> None:
    first = deterministic_item_id("doc", "entity", "explicit-key")
    assert first == deterministic_item_id("doc", "entity", "explicit-key")
    assert first != deterministic_item_id("other-doc", "entity", "explicit-key")
    assert "rev-a" not in first
    value = fixture()
    value["knowledge_revision"]["id"] = "rev-b"
    assert CanonicalKnowledgeSnapshot.model_validate(value).structure[0].id == fixture()["structure"][0]["id"]


def test_generated_schema_parity_and_fixture_validation() -> None:
    from jsonschema import Draft202012Validator

    text = SCHEMA.read_text(encoding="utf-8")
    assert text == generated_core_schema_text()
    schema = json.loads(text)
    assert schema["$id"] == "urn:docgrain:canonical-knowledge:0.1.0"
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for name in ("generic-pdf.json", "domain-example.json"):
        assert not list(validator.iter_errors(fixture(name)))
        CanonicalKnowledgeSnapshot.model_validate(fixture(name))


def test_explicit_domain_schema_validation_and_invalid_review_guard() -> None:
    value = fixture("domain-example.json")
    snapshot = CanonicalKnowledgeSnapshot.model_validate(value)
    schema = fixture("domain-example.schema.json")
    valid = validate_domain_record(snapshot.records[0], snapshot.domain_schemas[0], schema)
    assert valid.status == "valid"
    value["records"][0]["values"]["count"] = -2
    record = CanonicalKnowledgeSnapshot.model_validate(value).records[0]
    invalid = validate_domain_record(record, snapshot.domain_schemas[0], schema)
    assert invalid.status == "invalid" and invalid.errors
    value["records"][0]["validation"] = invalid.model_dump()
    CanonicalKnowledgeSnapshot.model_validate(value)
    value["records"][0]["annotation"]["review_status"] = "approved"
    with pytest.raises(ValidationError, match="invalid domain record cannot be approved"):
        CanonicalKnowledgeSnapshot.model_validate(value)
    schema["$ref"] = "https://example.com/schema"
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_domain_record(record, snapshot.domain_schemas[0], schema)
    pinned_with_ref = snapshot.domain_schemas[0].model_copy(update={
        "content_sha256": hashlib.sha256(canonical_json_bytes(schema)).hexdigest(),
    })
    with pytest.raises(ValueError, match="references are deferred"):
        validate_domain_record(record, pinned_with_ref, schema)
