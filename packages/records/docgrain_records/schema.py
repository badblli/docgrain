"""Typed proposal schemas compiled from reviewed workspace collection definitions."""

from .runtime import HOSPITALITY

CANDIDATES = list(HOSPITALITY.candidates.values())
ModelResponse = HOSPITALITY.response


def proposal_schema(collection: str | None = None, *, runtime=None) -> dict:
    return (runtime or HOSPITALITY).proposal_schema(collection)
