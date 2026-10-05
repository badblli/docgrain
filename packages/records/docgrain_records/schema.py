"""Typed model proposals; language alternatives precede deterministic placement."""

from functools import reduce
from operator import or_
from typing import Annotated, Literal, get_args

from pydantic import Field, create_model

from .models import RECORD_MODELS, StrictModel

# Fixed field names, typed values, and no free-form dictionaries in the model response.
# A list per field lets the model quote multiple languages without translating them.
CANDIDATES = []
for kind, (_, fields_model) in RECORD_MODELS.items():
    fields = {
        name: (list[get_args(field.annotation)[0]], Field())
        for name, field in fields_model.model_fields.items()
    }
    CANDIDATES.append(create_model(
        fields_model.__name__.replace("Fields", "Candidate"),
        __base__=StrictModel, type=(Literal[kind], ...), **fields,
    ))

Candidate = Annotated[reduce(or_, CANDIDATES), Field(discriminator="type")]


class ModelResponse(StrictModel):
    records: list[Candidate]


def proposal_schema(collection: str | None = None) -> dict:
    """OpenAI strict schema: all properties required, absent facts use empty lists."""
    if collection is None:
        schema = ModelResponse.model_json_schema()
    else:
        if collection not in RECORD_MODELS:
            raise ValueError("unknown record collection")
        candidate = CANDIDATES[list(RECORD_MODELS).index(collection)]
        response = create_model("FocusedResponse", __base__=StrictModel,
                                records=(list[candidate], ...))
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
