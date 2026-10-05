"""M2b executable schema/entity design spike."""

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest
from docgrain_domain.canonical import DomainSchemaRef, canonical_json_bytes
from docgrain_domain.canonical.entities import (
    RegisteredSchema,
    review_entity,
    validate_entity_data,
)
from docgrain_domain.canonical.entity_fields import leaf_pointers, resolve_pointer
from docgrain_domain.canonical.lifecycle import entity_id
from docgrain_domain.canonical.models import SchemaEntity

from tests.fixtures.entities import decision, entity_batch, registered_schema
from tests.fixtures.lifecycle import mapped_snapshot


def test_external_schema_validation_is_domain_independent():
    for schema_id, schema, valid, invalid in (
        ("hotel.room.v1", {"type": "object", "properties": {"capacity": {"type": "integer", "minimum": 1}},
                           "required": ["capacity"]}, {"capacity": 3}, {"capacity": "3"}),
        ("catalog.product.v1", {"type": "object", "properties": {"sku": {"type": "string"}},
                                "required": ["sku"]}, {"sku": "A-01"}, {}),
    ):
        registered = RegisteredSchema(workspace_id="workspace", reference=DomainSchemaRef(
            id=schema_id, version="1", content_sha256=sha256(canonical_json_bytes(schema)).hexdigest()),
            document=schema)
        assert validate_entity_data(valid, registered).status == "valid"
        assert validate_entity_data(invalid, registered).status == "invalid"


def entity_fixture(data=None, schema=None):
    snapshot, *_ = mapped_snapshot()
    schema = schema or registered_schema()
    batch = entity_batch(snapshot, schema, data)
    candidate = batch.entities[0]
    return SchemaEntity(id=entity_id(snapshot.document_id, schema.reference.id, candidate.identity_key),
                         schema_id=schema.reference.id, schema_version=schema.reference.version,
                         validation=validate_entity_data(candidate.data, schema), **candidate.model_dump())


def test_pointer_nested_arrays_escaping_and_complete_field_provenance():
    data = {"a/b": {"~x": [3, None, {}]}, "": [], "日本語": "value"}
    assert leaf_pointers(data) == {"/a~1b/~0x/0", "/a~1b/~0x/1", "/a~1b/~0x/2", "/", "/日本語"}
    assert resolve_pointer(data, "/a~1b/~0x/1") is None
    for path in ("a/b", "/a~2b", "/a~1b/~0x/00", "/missing", "/a~1b/~0x/-"):
        with pytest.raises(ValueError):
            resolve_pointer(data, path)
    schema = registered_schema(document={"type": "object"})
    value = entity_fixture(data, schema).model_dump(mode="json")
    SchemaEntity.model_validate(value)
    del value["field_annotations"]["/a~1b/~0x/1"]
    with pytest.raises(ValueError, match="cover every JSON leaf"):
        SchemaEntity.model_validate(value)
    invalid = entity_fixture().model_dump(mode="json")
    invalid["field_annotations"]["/name"]["provenance"]["evidence_ids"] = []
    with pytest.raises(ValueError, match="source evidence"):
        SchemaEntity.model_validate(invalid)


def test_schema_refs_dialect_formats_defaults_and_checksum():
    schema = registered_schema(document={"type": "object", "$defs": {"qty": {"type": "integer"}},
                                         "properties": {"count": {"$ref": "#/$defs/qty"},
                                                        "day": {"type": "string", "format": "date"},
                                                        "$ref": {"type": "string", "default": "value"}}})
    data = {"count": 2, "day": "2026-10-01"}
    original = copy.deepcopy(data)
    assert validate_entity_data(data, schema).status == "valid" and data == original
    assert validate_entity_data({"count": "2", "day": "bad-date"}, schema).status == "invalid"
    for document in ({"$ref": "https://example.com/schema"}, {"$dynamicRef": "https://example.com/schema"},
                     {"type": "object", "properties": {"x": {"format": "made-up-format"}}},
                     {"$schema": "https://json-schema.org/draft-07/schema"}, {"type": "not-a-type"}):
        with pytest.raises(ValueError):
            registered_schema(document=document)
    bad = schema.model_dump(mode="json")
    bad["document"]["title"] = "changed"
    with pytest.raises(ValueError, match="checksum"):
        RegisteredSchema.model_validate(bad)
    unresolved = registered_schema(document={"type": "object", "properties": {"x": {"$ref": "#/$defs/missing"}}})
    with pytest.raises(ValueError, match="cannot be resolved"):
        validate_entity_data({"x": 1}, unresolved)


def test_review_requires_history_valid_data_and_explicit_decisions():
    extracted = entity_fixture()
    with pytest.raises(ValueError, match="review transition"):
        review_entity(extracted, decision("extracted", "accepted"))
    pending = review_entity(extracted, decision("extracted", "needs_review"))
    accepted = review_entity(pending, decision("needs_review", "accepted"))
    assert accepted.data == extracted.data and accepted.id == extracted.id
    assert accepted.review_status == "accepted" and extracted.review_status == "extracted"
    with pytest.raises(ValueError, match="review transition"):
        review_entity(accepted, decision("accepted", "rejected"))
    invalid = entity_fixture({"name": "Example", "capacity": "3"})
    pending_invalid = review_entity(invalid, decision("extracted", "needs_review"))
    with pytest.raises(ValueError, match="schema-valid"):
        review_entity(pending_invalid, decision("needs_review", "accepted"))
    assert review_entity(pending_invalid, decision("needs_review", "rejected")).review_status == "rejected"
    forged = extracted.model_dump(mode="json")
    forged["review_status"] = "accepted"
    forged["annotation"]["review_status"] = "approved"
    with pytest.raises(ValueError, match="decision history"):
        SchemaEntity.model_validate(forged)
    measured = extracted.model_dump(mode="json")
    measured["field_annotations"]["/name"]["provenance"].update(confidence=0.9, confidence_method=None)
    with pytest.raises(ValueError, match="confidence_method"):
        SchemaEntity.model_validate(measured)


def test_generated_entity_and_projection_schemas_and_legacy_parity():
    from docgrain_domain.canonical.schema import (
        generated_core_schema_text,
        generated_lineage_schema_text,
    )
    from jsonschema import Draft202012Validator

    root = Path(__file__).resolve().parents[2] / "packages/domain/docgrain_domain/canonical/schemas"
    for version in ("0.2.0", "0.3.0", "0.4.0"):
        text = (root / f"canonical-knowledge-{version}.schema.json").read_text(encoding="utf-8")
        assert text == generated_core_schema_text(version)
        Draft202012Validator.check_schema(json.loads(text))
    for version in ("0.1.0", "0.2.0"):
        text = (root / f"derived-manifest-{version}.schema.json").read_text(encoding="utf-8")
        assert text == generated_lineage_schema_text(version)
        Draft202012Validator.check_schema(json.loads(text))


def test_entity_api_demo_is_read_only_and_never_fabricates_entities(monkeypatch):
    from docgrain_api.main import app
    from docgrain_api.settings import get_settings
    from fastapi.testclient import TestClient

    monkeypatch.setattr(get_settings(), "use_fixtures", True)
    client = TestClient(app)
    snapshot, *_ = mapped_snapshot()
    for path, body in (
        ("/v1/schemas", registered_schema().model_dump(mode="json")),
        ("/v1/knowledge/revisions/missing/entities", entity_batch(snapshot).model_dump(mode="json")),
        ("/v1/knowledge/revisions/missing/entities/missing/reviews", decision("extracted", "needs_review").model_dump(mode="json")),
        ("/v1/knowledge/revisions/missing/entities/missing/projection", None),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 409 and "read-only" in response.json()["detail"]
    for path in ("/v1/knowledge/revisions/missing/entities", "/v1/knowledge/derivations/missing",
                 "/v1/schemas/missing/versions/1?workspace_id=workspace-test"):
        assert client.get(path).status_code == 404
    malformed = registered_schema().model_dump(mode="json")
    malformed["document"]["$ref"] = "https://example.com/schema"
    malformed["reference"]["content_sha256"] = sha256(canonical_json_bytes(malformed["document"])).hexdigest()
    assert client.post("/v1/schemas", json=malformed).status_code == 422
