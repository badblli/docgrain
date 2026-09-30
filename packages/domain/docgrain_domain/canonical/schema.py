"""Generate the versioned core JSON Schema from Pydantic, never hand-maintain it."""

from __future__ import annotations

import json

from .models import CanonicalKnowledgeSnapshot

SCHEMA_ID = "urn:docgrain:canonical-knowledge:0.2.0"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def generated_core_schema(version: str = "0.2.0") -> dict[str, object]:
    if version not in {"0.2.0", "0.3.0"}:
        raise ValueError("unsupported generated schema version")
    schema = CanonicalKnowledgeSnapshot.model_json_schema(mode="validation")
    schema["$schema"] = DIALECT
    schema["$id"] = f"urn:docgrain:canonical-knowledge:{version}"
    schema["properties"]["schema_version"] = {"const": version, "title": "Schema Version", "type": "string"}
    if version == "0.2.0":
        schema["properties"]["identity_policy_version"]["const"] = "0.1.0"
        schema["properties"]["identity_policy_version"].pop("enum", None)
        schema["$defs"]["KnowledgeRevision"]["properties"].pop("processing")
        schema["$defs"].pop("ProcessingSpec")
    else:
        schema["properties"]["identity_policy_version"] = {
            "const": "0.2.0", "title": "Identity Policy Version", "type": "string"}
        schema["$defs"]["KnowledgeRevision"]["properties"]["processing"] = {"$ref": "#/$defs/ProcessingSpec"}
        schema["$defs"]["KnowledgeRevision"]["required"].append("processing")
    return schema


def generated_core_schema_text(version: str = "0.2.0") -> str:
    return json.dumps(generated_core_schema(version), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def generated_lineage_schema_text() -> str:
    from .lineage import DerivedManifest

    schema = DerivedManifest.model_json_schema(mode="validation")
    schema["$schema"] = DIALECT
    schema["$id"] = "urn:docgrain:derived-manifest:0.1.0"
    return json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
