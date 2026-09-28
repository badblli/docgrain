"""Optional, explicit domain-schema validation; never discovers schemas or fetches refs."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from pydantic import JsonValue

from .identity import canonical_json_bytes
from .models import DomainRecord, DomainSchemaRef, DomainValidationResult


def _reject_references(value: JsonValue) -> None:
    if isinstance(value, dict):
        if "$ref" in value or "$dynamicRef" in value or "$recursiveRef" in value:
            raise ValueError("domain schema references are deferred in v0.1")
        for child in value.values():
            _reject_references(child)
    elif isinstance(value, list):
        for child in value:
            _reject_references(child)


def validate_domain_record(
    record: DomainRecord,
    schema_ref: DomainSchemaRef,
    schema_document: Mapping[str, JsonValue],
) -> DomainValidationResult:
    """The caller supplies a pinned schema document; no registry or network access exists here."""
    if record.schema_id != schema_ref.id:
        raise ValueError("record and schema reference differ")
    materialized = dict(schema_document)
    digest = hashlib.sha256(canonical_json_bytes(materialized)).hexdigest()
    if digest != schema_ref.content_sha256:
        raise ValueError("domain schema checksum mismatch")
    _reject_references(materialized)
    # Optional dependency is intentionally confined to this boundary.
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(materialized)
    validator = Draft202012Validator(materialized)
    errors = sorted(
        f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
         for error in validator.iter_errors(record.values)
    )
    return DomainValidationResult(status="invalid", errors=errors) if errors else DomainValidationResult(status="valid")
