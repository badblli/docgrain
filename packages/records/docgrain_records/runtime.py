"""Isolated runtime models compiled from an accepted workspace collection schema."""

import json
from functools import reduce
from operator import or_
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import Field, SerializeAsAny, TypeAdapter, create_model

from .models import (
    RECORD_MODELS,
    ExtractionResult,
    FieldValue,
    Language,
    RecordBase,
    StrictModel,
    Text,
)

RESERVED = {"id", "type", "i18n", "conflicts", "review_state", "_meta"}


def _scalar(node):
    """Compile the JSON Schema subset emitted by collection discovery, fail closed."""
    types = {"string": Text, "integer": int, "number": float, "boolean": bool}
    if node.get("type") in types:
        return types[node["type"]]
    if node == {"type": "array", "items": {"type": "string"}}:
        return list[Text]
    raise ValueError("unsupported collection value schema")


def _identity(fields, key):
    fact = getattr(fields, key)
    if fact is None:
        return None
    value = fact.value if isinstance(fact.value, str) else json.dumps(fact.value, ensure_ascii=False)
    return FieldValue[Text](value=value, lang=fact.lang, evidence=fact.evidence)


class RuntimeRecords:
    """No global registry mutation: two workspaces may use identical keys differently."""

    def __init__(self, schema=None):
        self.schema = None
        self.models = {}
        self.identities = {}
        self._merge_model = None
        if schema is None:
            definitions = {kind: (fields, "name") for kind, (_, fields) in RECORD_MODELS.items()}
            self.collections = {"property": "properties", "room_type": "rooms", "outlet": "outlets",
                                "activity": "activities", "facility": "facilities", "policy": "policies",
                                "contact": "contacts", "service_price": "service_prices"}
            self.focused = ("policy", "service_price", "activity", "facility")
        else:
            # Imported lazily: discovery reuses extractor quotation verification.
            from .discovery_models import WorkspaceSchema, collection_record_schema

            schema = WorkspaceSchema.model_validate_json(
                schema.model_dump_json() if isinstance(schema, WorkspaceSchema) else json.dumps(schema))
            if schema.review_state != "accepted" or schema.version is None or not schema.collections:
                raise ValueError("runtime requires a nonempty accepted workspace schema version")
            definitions = {}
            for collection in schema.collections:
                contract = collection_record_schema(schema, collection.key)
                properties = contract["properties"]
                if any(key in RESERVED or key.startswith("_") or hasattr(RecordBase, key)
                       for key in properties):
                    raise ValueError("collection schema uses a reserved record field")
                annotations = {key: (FieldValue[_scalar(node["anyOf"][0]["properties"]["value"])]
                                     | None, None) for key, node in properties.items()}
                # Discovery does not require a field called name. Its first field is the
                # identity fallback; it must have evidence, just like hospitality names.
                identity = "name" if "name" in properties else next(iter(properties))
                fields = create_model(collection.key + "Fields", __base__=StrictModel, **annotations)
                if identity != "name":
                    fields.name = property(lambda item, key=identity: _identity(item, key))
                definitions[collection.key] = fields, identity
            self.schema = schema.model_dump(mode="json")
            self.collections = {key: key for key in definitions}
            self.focused = tuple(definitions)
        self.candidates = {}
        for key, (fields, identity) in definitions.items():
            base = RECORD_MODELS[key][0] if self.schema is None else (fields, RecordBase)
            model = create_model(key + "Record", __base__=base,
                                 type=(Literal[key], key),
                                 i18n=(dict[Language, fields], Field(default_factory=dict)))
            self.models[key] = model, fields
            self.identities[key] = identity
            self.candidates[key] = create_model(
                key + "Candidate", __base__=StrictModel, type=(Literal[key], ...),
                **{name: (list[get_args(field.annotation)[0]], ...)
                   for name, field in fields.model_fields.items()})
        self.response = self._response(tuple(self.candidates))
        union = self._union([model for model, _ in self.models.values()])
        self.result = create_model(
            "WorkspaceExtractionResult", __base__=ExtractionResult, records=(list[union], ...),
            **({"domain": (Literal["workspace"], "workspace"),
                "workspace_schema": (dict, self.schema)} if self.schema else {}))

    @staticmethod
    def _union(models):
        if len(models) == 1:
            return models[0]
        return Annotated[reduce(or_, models), Field(discriminator="type")]

    def _response(self, keys):
        return create_model("CollectionResponse", __base__=StrictModel,
                            records=(list[self._union([self.candidates[key] for key in keys])], ...))

    def proposal_schema(self, collection=None):
        if collection is not None and collection not in self.models:
            raise ValueError("unknown record collection")
        response = self.response if collection is None else self._response((collection,))
        schema = response.model_json_schema()

        def strict(node):
            if isinstance(node, dict):
                node.pop("default", None)
                node.pop("discriminator", None)
                if "oneOf" in node:
                    node["anyOf"] = node.pop("oneOf")
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

    def validate_value(self, kind, field, value):
        if kind not in self.models or field not in self.models[kind][1].model_fields:
            raise ValueError("unknown or reserved record field")
        fact = get_args(self.models[kind][1].model_fields[field].annotation)[0]
        value_field = fact.model_fields["value"]
        annotation = (Annotated[value_field.annotation, *value_field.metadata]
                      if value_field.metadata else value_field.annotation)
        return TypeAdapter(annotation).validate_python(value, strict=True)

    def merge_document(self, value):
        from .merge_models import MergeDocument, SourceRecord

        if self._merge_model is None:
            union = self._union([model for model, _ in self.models.values()])
            source = create_model("WorkspaceSourceRecord", __base__=SourceRecord,
                                  record=(SerializeAsAny[union], ...))
            self._merge_model = create_model("WorkspaceMergeDocument", __base__=MergeDocument,
                                            records=(list[source], ...))
        return self._merge_model.model_validate(value)


HOSPITALITY = RuntimeRecords()


def load_runtime(path):
    return RuntimeRecords(json.loads(Path(path).read_text(encoding="utf-8")))


def revision_runtime(revision):
    runtime = RuntimeRecords(revision.workspace_schema) if revision.workspace_schema else HOSPITALITY
    if runtime.schema and runtime.schema["workspace_id"] != revision.workspace_id:
        raise ValueError("collection schema belongs to another workspace")
    return runtime
