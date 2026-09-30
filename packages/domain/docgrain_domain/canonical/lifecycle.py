"""Revision identities; logical source identity is supplied explicitly by the caller."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue, model_validator

from .identity import canonical_json_bytes
from .locations import StrictModel


def digest(value: JsonValue) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def scoped_id(kind: str, parts: list[JsonValue]) -> str:
    if not kind or any(part == "" for part in parts):
        raise ValueError("identity components must be nonempty")
    return f"{kind}_{digest(['lifecycle-0.1.0', kind, *parts])[:32]}"


def logical_document_id(workspace_id: str, connector: str, source_key: str) -> str:
    """Explicit connector natural key; never guess identity from filenames."""
    return scoped_id("document", [workspace_id, connector, source_key])


def source_revision_id(workspace_id: str, document_id: str, content_sha256: str) -> str:
    if len(content_sha256) != 64 or any(c not in "0123456789abcdef" for c in content_sha256):
        raise ValueError("source content must have a lowercase SHA-256")
    return scoped_id("source", [workspace_id, document_id, content_sha256])


class ProcessingSpec(StrictModel):
    """All output-affecting implementation versions and effective settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    parser: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    dependencies: dict[str, str] = Field(default_factory=dict)
    options: dict[str, JsonValue] = Field(default_factory=dict)
    mapper_version: str = Field(default="m2a-1", min_length=1)
    schema_version: Literal["0.3.0", "0.4.0"] = "0.3.0"
    identity_policy_version: Literal["0.2.0"] = "0.2.0"

    @property
    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))


def processing_revision_id(source_id: str, spec: ProcessingSpec) -> str:
    return scoped_id("revision", [source_id, spec.digest])


class DerivedRevision(StrictModel):
    """Separate immutable chunking/embedding/indexing runs; no runtime backend types."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    processing_revision_id: str = Field(min_length=1)
    stage: Literal["projection", "chunking", "embedding", "indexing"]
    upstream_revision_ids: tuple[str, ...] = Field(min_length=1)
    strategy: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    configuration: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def configuration_digest(self) -> str:
        return digest({"strategy": self.strategy, "version": self.strategy_version,
                       "configuration": self.configuration})

    def expected_id(self) -> str:
        return scoped_id(self.stage, [self.workspace_id, self.document_id, self.processing_revision_id,
                                     sorted(self.upstream_revision_ids), self.configuration_digest])

    @model_validator(mode="after")
    def deterministic_identity(self) -> DerivedRevision:
        if len(set(self.upstream_revision_ids)) != len(self.upstream_revision_ids):
            raise ValueError("duplicate upstream revisions")
        if self.id != self.expected_id():
            raise ValueError("derived revision ID differs from its scoped configuration")
        return self

    @classmethod
    def create(cls, **values) -> DerivedRevision:
        provisional = cls.model_construct(id="pending", **values)
        return cls.model_validate({"id": provisional.expected_id(), **values})


def chunk_id(document_id: str, parent_ids: list[str], strategy: str, strategy_version: str,
             ordinal: int, content_sha256: str) -> str:
    if not parent_ids or any(not key for key in parent_ids) or ordinal < 0:
        raise ValueError("chunk requires ordered parents and a nonnegative ordinal")
    if len(content_sha256) != 64 or any(c not in "0123456789abcdef" for c in content_sha256):
        raise ValueError("chunk content must have a lowercase SHA-256")
    return scoped_id("chunk", [document_id, parent_ids, strategy, strategy_version, ordinal, content_sha256])


def entity_id(document_id: str, schema_id: str, natural_key: str) -> str:
    """Caller-owned schema/business key, with no implicit fuzzy matching."""
    return scoped_id("entity", [document_id, schema_id, natural_key])
