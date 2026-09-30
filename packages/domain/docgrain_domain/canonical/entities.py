"""External schema validation and entity review; no extraction provider or network access."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from pydantic import ConfigDict, Field, JsonValue, model_validator

from .entity_fields import pointer
from .identity import canonical_json_bytes
from .locations import StrictModel
from .models import (
    DomainSchemaRef,
    DomainValidationResult,
    EntityReviewEvent,
    SchemaEntity,
)

_MAP_SCHEMAS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
_ARRAY_SCHEMAS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_SINGLE_SCHEMAS = {"items", "contains", "additionalProperties", "unevaluatedProperties", "unevaluatedItems",
                   "propertyNames", "not", "if", "then", "else", "contentSchema"}


def _check_offline_schema(schema, formats):
    if not isinstance(schema, dict):
        return
    for key in ("$ref", "$dynamicRef", "$recursiveRef"):
        if key in schema and (not isinstance(schema[key], str) or not schema[key].startswith("#")):
            raise ValueError("only local schema references are supported; external references are disabled")
    if "$schema" in schema and schema["$schema"] != "https://json-schema.org/draft/2020-12/schema":
        raise ValueError("only Draft 2020-12 schema dialect is supported")
    if "format" in schema and schema["format"] not in formats:
        raise ValueError(f"unsupported JSON Schema format: {schema['format']}")
    for key in _MAP_SCHEMAS:
        for child in schema.get(key, {}).values():
            _check_offline_schema(child, formats)
    for key in _ARRAY_SCHEMAS:
        for child in schema.get(key, []):
            _check_offline_schema(child, formats)
    for key in _SINGLE_SCHEMAS:
        if key in schema:
            _check_offline_schema(schema[key], formats)


class RegisteredSchema(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace_id: str = Field(min_length=1)
    reference: DomainSchemaRef
    document: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_document(self) -> RegisteredSchema:
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError

        if sha256(canonical_json_bytes(self.document)).hexdigest() != self.reference.content_sha256:
            raise ValueError("schema checksum mismatch")
        try:
            Draft202012Validator.check_schema(self.document)
        except SchemaError as exc:
            raise ValueError(f"invalid JSON Schema: {exc.message}") from exc
        _check_offline_schema(self.document, FormatChecker().checkers)
        return self


def validate_entity_data(data: dict[str, JsonValue], schema: RegisteredSchema) -> DomainValidationResult:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry
    from referencing.exceptions import Unresolvable
    from referencing.jsonschema import DRAFT202012

    schema = RegisteredSchema.model_validate(schema.model_dump(mode="json"))
    resource = DRAFT202012.create_resource(schema.document)
    registry = Registry().with_resource(schema.document.get("$id", "urn:docgrain:entity-schema"), resource)
    validator = Draft202012Validator(schema.document, format_checker=FormatChecker(), registry=registry)
    try:
        errors = sorted(f"{pointer(error.absolute_path) or '<root>'}: {error.message}"
                        for error in validator.iter_errors(data))
    except Unresolvable as exc:
        raise ValueError("schema local reference cannot be resolved") from exc
    return DomainValidationResult(status="invalid", errors=errors) if errors else DomainValidationResult(status="valid")


def review_entity(entity: SchemaEntity, event: EntityReviewEvent) -> SchemaEntity:
    payload = deepcopy(entity.model_dump(mode="json"))
    payload["review_events"].append(event.model_dump(mode="json"))
    payload["review_status"] = event.to_status
    payload["annotation"]["review_status"] = {"needs_review": "proposed", "accepted": "approved", "rejected": "rejected"}.get(event.to_status, "proposed")
    return SchemaEntity.model_validate(payload)
