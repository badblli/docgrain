"""Generate the versioned core JSON Schema from Pydantic, never hand-maintain it."""

from __future__ import annotations

import json

from .models import CanonicalKnowledgeSnapshot

SCHEMA_ID = "urn:docgrain:canonical-knowledge:0.2.0"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def generated_core_schema() -> dict[str, object]:
    schema = CanonicalKnowledgeSnapshot.model_json_schema(mode="validation")
    schema["$schema"] = DIALECT
    schema["$id"] = SCHEMA_ID
    schema["properties"]["schema_version"] = {"const": "0.2.0", "title": "Schema Version", "type": "string"}
    return schema


def generated_core_schema_text() -> str:
    return json.dumps(generated_core_schema(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
