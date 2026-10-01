"""Version-pinned embedding boundary and immutable materialized index generations."""

from __future__ import annotations

import math
from typing import Literal, Protocol

from pydantic import Field, JsonValue, StrictFloat, model_validator

from .chunking import ChunkingSpec, ChunkSet
from .lifecycle import DerivedRevision, digest, scoped_id
from .lineage import ChunkPayload, DerivedManifest, LineageEdge, ObjectRef
from .locations import StrictModel


class EmbeddingSpec(StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    version: str = Field(min_length=1)
    dimensions: int = Field(ge=1, le=65536)
    options: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def digest(self):
        return digest(self.model_dump(mode="json"))

    def validate_vector(self, vector):
        if len(vector) != self.dimensions or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                                 or not math.isfinite(v) for v in vector):
            raise ValueError("embedding must contain finite numbers with configured dimensions")
        return [float(v) for v in vector]


class Embedder(Protocol):
    """Adapters must honor the supplied version/configuration; there is no default adapter."""

    def embed(self, text: str, spec: EmbeddingSpec) -> list[float]: ...


class IndexSpec(StrictModel):
    name: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,100}$")
    chunking: ChunkingSpec = Field(default_factory=ChunkingSpec)
    embedding: EmbeddingSpec


def embedding_cache_key(workspace_id, document_id, spec: EmbeddingSpec, content_sha256):
    return scoped_id("embedding-cache", [workspace_id, document_id, spec.digest, content_sha256])


def generation_revision(chunk_set: ChunkSet, spec: IndexSpec, base_id: str | None, full: bool):
    chunking = chunk_set.revision
    embedding = DerivedRevision.create(workspace_id=chunking.workspace_id, document_id=chunking.document_id,
                                       processing_revision_id=chunking.processing_revision_id, stage="embedding",
                                       upstream_revision_ids=(chunking.id,), strategy="retrieval-text",
                                       strategy_version="1", configuration=spec.embedding.model_dump(mode="json"))
    indexing = DerivedRevision.create(workspace_id=chunking.workspace_id, document_id=chunking.document_id,
                                      processing_revision_id=chunking.processing_revision_id, stage="indexing",
                                      upstream_revision_ids=(chunking.id, embedding.id), strategy="postgres-generation",
                                      strategy_version="1", configuration={"spec": spec.model_dump(mode="json"),
                                                                          "base_id": base_id, "full": full})
    return embedding, indexing


class IndexEntry(StrictModel):
    chunk: ChunkPayload
    embedding_ref: ObjectRef
    index_ref: ObjectRef
    vector: list[StrictFloat] = Field(min_length=1)


class IndexGeneration(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    spec: IndexSpec
    base_id: str | None
    full: bool = False
    chunk_set: ChunkSet
    embedding_revision: DerivedRevision
    revision: DerivedRevision
    entries: list[IndexEntry]
    embedded_chunk_ids: list[str]
    reused_chunk_ids: list[str]
    removed_chunk_ids: list[str]

    @model_validator(mode="after")
    def verified(self):
        embedding, indexing = generation_revision(self.chunk_set, self.spec, self.base_id, self.full)
        if self.embedding_revision != embedding or self.revision != indexing:
            raise ValueError("index generation revision/configuration mismatch")
        if [e.chunk for e in self.entries] != self.chunk_set.chunks:
            raise ValueError("index must contain every canonical chunk exactly once in reading order")
        ids = [e.chunk.object_ref.object_id for e in self.entries]
        embedded, reused = self.embedded_chunk_ids, self.reused_chunk_ids
        if (len(set(ids)) != len(ids) or len(set(embedded + reused)) != len(embedded + reused)
                or set(embedded + reused) != set(ids) or self.full and reused):
            raise ValueError("embedding/reuse accounting must partition entries")
        if len(set(self.removed_chunk_ids)) != len(self.removed_chunk_ids) or set(ids) & set(self.removed_chunk_ids):
            raise ValueError("removed entries must be unique and absent from generation")
        for entry in self.entries:
            if entry.embedding_ref != entry_refs(entry.chunk, embedding, indexing)[0] or entry.index_ref != entry_refs(entry.chunk, embedding, indexing)[1]:
                raise ValueError("index entry occurrence identity mismatch")
            self.spec.embedding.validate_vector(entry.vector)
        return self

    def manifests(self):
        """Actual payload-backed lineage; empty generations have no invented objects."""
        if not self.entries:
            return []
        return [self.chunk_set.manifest(),
                DerivedManifest(revision=self.embedding_revision, objects=[e.embedding_ref for e in self.entries],
                                edges=[LineageEdge(upstream=e.chunk.object_ref, downstream=e.embedding_ref) for e in self.entries]),
                DerivedManifest(revision=self.revision, objects=[e.index_ref for e in self.entries],
                                edges=[LineageEdge(upstream=p, downstream=e.index_ref) for e in self.entries
                                       for p in (e.chunk.object_ref, e.embedding_ref)])]


def entry_refs(chunk, embedding, indexing):
    key = chunk.object_ref.object_id
    return (ObjectRef(kind="embedding", revision_id=embedding.id,
                      object_id=scoped_id("embedding-object", [embedding.document_id, key, embedding.configuration_digest])),
            ObjectRef(kind="index", revision_id=indexing.id,
                      object_id=scoped_id("index-object", [indexing.document_id, key, indexing.configuration_digest])))
