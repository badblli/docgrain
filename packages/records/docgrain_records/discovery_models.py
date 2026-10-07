"""Workspace collection contracts, independent of industry/domain packs."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .api import SourceMetadata
from .models import Evidence, Language, StrictModel, Text

Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")]
CollectionKey = Annotated[str, Field(
    pattern=r"^(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)*s|(?:[a-z][a-z0-9]*_)*(?:people|children|men|women|teeth|feet|mice|geese))$",
)]
FieldType = Literal["string", "integer", "number", "boolean", "string_list"]
ReviewState = Literal["proposed", "needs_review", "accepted", "rejected"]


class Label(StrictModel):
    lang: Language
    value: Text


class Definition(StrictModel):
    key: Key
    type: FieldType
    unit: Text | None
    label_i18n: list[Label] = Field(min_length=1)

    @model_validator(mode="after")
    def labels(self):
        languages = [label.lang for label in self.label_i18n]
        if "en" not in languages or len(languages) != len(set(languages)):
            raise ValueError("labels require English and unique languages")
        return self


class ExampleValue(StrictModel):
    key: Key
    value: Text | int | float | bool | list[Text]
    lang: Language
    evidence: list[Evidence] = Field(min_length=1)


class Example(StrictModel):
    values: list[ExampleValue] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_values(self):
        keys = [(value.key, value.lang) for value in self.values]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate example field/language")
        return self


class CollectionProposal(StrictModel):
    key: CollectionKey
    label_i18n: list[Label] = Field(min_length=1)
    description: Text
    fields: list[Definition] = Field(min_length=1)
    examples: list[Example] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def contract(self):
        languages = [label.lang for label in self.label_i18n]
        if "en" not in languages or len(languages) != len(set(languages)):
            raise ValueError("labels require English and unique languages")
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate field definition")
        return self


class DiscoveryResponse(StrictModel):
    collections: list[CollectionProposal]


class CollectionField(Definition):
    review_state: ReviewState = "proposed"
    alternatives: list[Definition] = Field(default_factory=list)


class Collection(CollectionProposal):
    fields: list[CollectionField] = Field(min_length=1)
    review_state: ReviewState = "proposed"
    # Missing in legacy versions: retain their name/first-field behaviour.
    identity: Key | None = None

    @model_validator(mode="after")
    def identity_field(self):
        if self.identity is not None and self.identity not in {f.key for f in self.fields}:
            raise ValueError("identity must be a retained collection field")
        return self


class DiscoverySource(SourceMetadata):
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DiscoveryDocument(StrictModel):
    source: SourceMetadata
    context: Text


class RejectedExample(StrictModel):
    collection: Key
    example_index: int = Field(ge=0)
    field: Key
    reason: Literal["document_mismatch", "locator_not_found", "quote_not_found",
                    "unknown_field", "type_mismatch"]


class WorkspaceSchema(StrictModel):
    format: Literal["docgrain.workspace-schema"] = "docgrain.workspace-schema"
    workspace_id: Text
    version: int | None = Field(default=None, ge=1)
    review_state: Literal["proposed", "accepted"] = "proposed"
    sources: list[DiscoverySource]
    collections: list[Collection]
    rejected: list[RejectedExample] = Field(default_factory=list)
    coverage: float = Field(default=0, ge=0, le=1)
    uncovered: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [collection.key for collection in self.collections]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate collection key")
        for collection in self.collections:
            fields = [field.key for field in collection.fields]
            if len(fields) != len(set(fields)):
                raise ValueError("duplicate collection field key")
        documents = [source.document_id for source in self.sources]
        if len(documents) != len(set(documents)) or any(
            source.workspace_id != self.workspace_id for source in self.sources
        ):
            raise ValueError("schema sources must be unique and belong to its workspace")
        return self


def discovery_schema() -> dict:
    """Strict compatible model output: no arbitrary object properties or review authority."""
    schema = DiscoveryResponse.model_json_schema()

    def strict(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for child in node.values():
                strict(child)
        elif isinstance(node, list):
            for child in node:
                strict(child)

    strict(schema)
    return schema


def collection_record_schema(schema: WorkspaceSchema, key: str) -> dict:
    """Runtime record contract generated ONLY from a reviewed workspace schema."""
    if schema.review_state != "accepted" or schema.version is None:
        raise ValueError("runtime record schema requires an accepted workspace version")
    collection = next((item for item in schema.collections if item.key == key), None)
    if collection is None or collection.review_state != "accepted":
        raise ValueError("collection is not accepted in this workspace schema")
    evidence = Evidence.model_json_schema()
    properties = {}
    for field in collection.fields:
        if field.review_state != "accepted" or field.alternatives:
            raise ValueError("runtime schema contains an unresolved field")
        scalar = {"type": field.type if field.type != "string_list" else "array"}
        if field.type == "string_list":
            scalar["items"] = {"type": "string"}
        value = {"type": "object", "additionalProperties": False,
                 "required": ["value", "lang", "evidence"], "properties": {
                     "value": scalar, "lang": {"type": "string"},
                     "evidence": {"type": "array", "minItems": 1, "items": evidence},
                 }}
        properties[field.key] = {"anyOf": [value, {"type": "null"}]}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{key} (workspace schema v{schema.version})",
            "type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}
