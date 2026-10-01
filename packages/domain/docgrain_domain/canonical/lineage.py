"""Revision-qualified lineage DAG and forward/backward query contract."""

from __future__ import annotations

from collections import deque
from hashlib import sha256
from typing import Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from .lifecycle import DerivedRevision, scoped_id
from .locations import StrictModel
from .models import CanonicalKnowledgeSnapshot

ObjectKind = Literal["source", "processing", "canonical", "projection", "chunk", "embedding", "index"]
_ORDER = {"source": 0, "processing": 1, "canonical": 2, "projection": 3, "chunk": 4, "embedding": 5, "index": 6}
_OUTPUT = {"projection": "projection", "chunking": "chunk", "embedding": "embedding", "indexing": "index"}
_INPUT = {"projection": {"canonical"}, "chunk": {"canonical", "projection"}, "embedding": {"chunk"}, "index": {"chunk", "embedding"}}


class ObjectRef(StrictModel):
    kind: ObjectKind
    revision_id: str = Field(min_length=1)
    object_id: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return scoped_id("occurrence", [self.kind, self.revision_id, self.object_id])


class LineageEdge(StrictModel):
    upstream: ObjectRef
    downstream: ObjectRef

    @model_validator(mode="after")
    def ordered(self) -> LineageEdge:
        if _ORDER[self.upstream.kind] >= _ORDER[self.downstream.kind]:
            raise ValueError("lineage edges must advance lifecycle stages")
        return self


class ProjectionArtifact(StrictModel):
    object_ref: ObjectRef
    role: Literal["retrieval-text"] = "retrieval-text"
    mime_type: Literal["application/json"] = "application/json"
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str

    @model_validator(mode="after")
    def verified_payload(self) -> ProjectionArtifact:
        if self.object_ref.kind != "projection" or sha256(self.text.encode()).hexdigest() != self.content_sha256:
            raise ValueError("projection artifact kind or content checksum mismatch")
        return self


class ChunkContext(StrictModel):
    object_ref: ObjectRef
    kind: Literal["document", "section", "list", "table_caption", "entity_label"]
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class ChunkSource(StrictModel):
    object_ref: ObjectRef
    kind: Literal["whole", "text", "rows", "entity_fields"]
    evidence_ids: list[str] = Field(default_factory=list)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    field_pointers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def slice_contract(self) -> ChunkSource:
        if self.object_ref.kind != "canonical":
            raise ValueError("chunk source must be canonical")
        if self.kind in {"text", "rows"}:
            if self.start is None or self.end is None or self.end <= self.start:
                raise ValueError("chunk source slice must be a nonempty half-open interval")
        elif self.start is not None or self.end is not None:
            raise ValueError("whole/entity sources cannot carry slice offsets")
        if (self.kind == "entity_fields") != bool(self.field_pointers):
            raise ValueError("only entity sources require field pointers")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("duplicate chunk source evidence")
        return self


def contextualize_chunk(text: str, context: list[ChunkContext]) -> str:
    prefix = "\n".join(item.text for item in context if item.text)
    return prefix + "\n\n" + text if prefix else text


class ChunkPayload(StrictModel):
    object_ref: ObjectRef
    kind: Literal["text", "table", "entity", "description"]
    order: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)
    retrieval_text: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    character_count: int = Field(ge=1)
    oversized: bool = False
    split_fallback: bool = False
    parents: list[ObjectRef] = Field(min_length=1)
    context: list[ChunkContext] = Field(default_factory=list)
    sources: list[ChunkSource] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_payload(self) -> ChunkPayload:
        if self.object_ref.kind != "chunk" or self.retrieval_text != contextualize_chunk(self.text, self.context):
            raise ValueError("chunk kind or contextualized text mismatch")
        if self.character_count != len(self.retrieval_text) or sha256(self.retrieval_text.encode()).hexdigest() != self.content_sha256:
            raise ValueError("chunk size or checksum mismatch")
        parents = {parent.key for parent in self.parents}
        required = {item.object_ref.key for item in [*self.context, *self.sources]}
        if len(parents) != len(self.parents) or parents != required or any(p.kind != "canonical" for p in self.parents):
            raise ValueError("chunk parents must cover context and sources exactly")
        evidence = {ref for item in [*self.context, *self.sources] for ref in item.evidence_ids}
        if len(self.evidence_ids) != len(set(self.evidence_ids)) or set(self.evidence_ids) != evidence:
            raise ValueError("chunk evidence must cover context and sources exactly")
        return self


class ChunkOmission(StrictModel):
    object_ref: ObjectRef
    reason: Literal["empty_text", "no_description", "unaccepted_entity", "invalid_entity", "legacy_entity", "entity_disabled"]


class DerivedManifest(StrictModel):
    schema_version: Literal["0.1.0", "0.2.0", "0.3.0"] = "0.1.0"
    revision: DerivedRevision
    objects: list[ObjectRef] = Field(min_length=1)
    edges: list[LineageEdge] = Field(min_length=1)
    projections: list[ProjectionArtifact] = Field(default_factory=list)
    chunks: list[ChunkPayload] = Field(default_factory=list)
    chunk_omissions: list[ChunkOmission] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def serialize_manifest(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        payload = handler(self)
        if not self.projections:
            payload.pop("projections", None)
        for field in ("chunks", "chunk_omissions"):
            if not getattr(self, field):
                payload.pop(field, None)
        return payload

    @model_validator(mode="after")
    def validate_members(self) -> DerivedManifest:
        keys = {obj.key for obj in self.objects}
        if len(keys) != len(self.objects):
            raise ValueError("duplicate derived objects")
        output_kind = _OUTPUT[self.revision.stage]
        if self.schema_version != "0.3.0" and (self.chunks or self.chunk_omissions):
            raise ValueError("chunk payloads require derived manifest schema_version 0.3.0")
        if self.schema_version == "0.3.0" and output_kind == "chunk":
            if [chunk.object_ref for chunk in self.chunks] != self.objects:
                raise ValueError("chunk stage requires ordered payloads for every object")
            if [chunk.order for chunk in self.chunks] != list(range(len(self.chunks))):
                raise ValueError("chunk reading order must be contiguous")
            expected_edges = {(parent.key, chunk.object_ref.key) for chunk in self.chunks for parent in chunk.parents}
            if {(edge.upstream.key, edge.downstream.key) for edge in self.edges} != expected_edges:
                raise ValueError("chunk lineage must cover payload parents exactly")
        elif self.chunks or self.chunk_omissions:
            raise ValueError("chunk payloads require chunking stage")
        if self.schema_version == "0.1.0" and (
            output_kind == "projection" or self.projections
            or any(edge.upstream.kind == "projection" for edge in self.edges)
        ):
            raise ValueError("projections require derived manifest schema_version 0.2.0")
        if output_kind == "projection":
            if {artifact.object_ref.key for artifact in self.projections} != keys or len(self.projections) != len(keys):
                raise ValueError("projection stage requires one verified artifact for every object")
        elif self.projections:
            raise ValueError("projection payloads require projection stage")
        if any(obj.kind != output_kind or obj.revision_id != self.revision.id for obj in self.objects):
            raise ValueError("derived object kind/revision must match manifest")
        upstreams: set[str] = set()
        targets: set[str] = set()
        edge_keys: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.downstream.key not in keys or edge.upstream.kind not in _INPUT[output_kind]:
                raise ValueError("invalid derived dependency stage or target")
            pair = (edge.upstream.key, edge.downstream.key)
            if pair in edge_keys:
                raise ValueError("duplicate lineage edges")
            edge_keys.add(pair)
            upstreams.add(edge.upstream.revision_id)
            targets.add(edge.downstream.key)
        if upstreams != set(self.revision.upstream_revision_ids) or targets != keys:
            raise ValueError("every declared upstream revision and derived object must have dependency edges")
        return self


class LineageTrace(StrictModel):
    workspace_id: str
    document_id: str
    processing_revision_id: str
    start: ObjectRef
    direction: Literal["upstream", "downstream"]
    objects: list[ObjectRef]
    edges: list[LineageEdge]
    depth_limited: bool = False


class LineageGraph:
    """One canonical revision and its registered downstream manifests only."""

    def __init__(self, snapshot: CanonicalKnowledgeSnapshot):
        self.snapshot = snapshot
        source = ObjectRef(kind="source", revision_id=snapshot.source_version.id,
                           object_id=snapshot.document_id)
        processing = ObjectRef(kind="processing", revision_id=snapshot.knowledge_revision.id,
                               object_id=snapshot.document_id)
        objects = [source, processing]
        self.edges = [LineageEdge(upstream=source, downstream=processing)]
        for collection in (snapshot.structure, snapshot.entities, snapshot.relations,
                           snapshot.records, snapshot.artifacts):
            for item in collection:
                ref = ObjectRef(kind="canonical", revision_id=snapshot.knowledge_revision.id, object_id=item.id)
                objects.append(ref)
                self.edges.append(LineageEdge(upstream=processing, downstream=ref))
        self.objects = {obj.key: obj for obj in objects}

    def extend(self, manifest: DerivedManifest) -> None:
        manifest = DerivedManifest.model_validate(manifest.model_dump(mode="json"))
        revision = manifest.revision
        if (revision.workspace_id, revision.document_id, revision.processing_revision_id) != (
            self.snapshot.workspace_id, self.snapshot.document_id, self.snapshot.knowledge_revision.id
        ):
            raise ValueError("lineage document/workspace/processing scope mismatch")
        if any(obj.key in self.objects for obj in manifest.objects):
            raise ValueError("derived occurrence already registered")
        if any(edge.upstream.key not in self.objects for edge in manifest.edges):
            raise ValueError("unknown upstream occurrence")
        self.objects.update({obj.key: obj for obj in manifest.objects})
        self.edges.extend(manifest.edges)

    def trace(self, start: ObjectRef, direction: Literal["upstream", "downstream"], *,
              max_depth: int = 16, max_objects: int = 1000) -> LineageTrace:
        if direction not in {"upstream", "downstream"} or not 1 <= max_depth <= 32 or not 1 <= max_objects <= 2000:
            raise ValueError("invalid lineage traversal bounds")
        if start.key not in self.objects:
            raise KeyError("lineage object not found in this processing revision")
        adjacency: dict[str, list[tuple[str, LineageEdge]]] = {}
        for edge in self.edges:
            origin, target = ((edge.upstream, edge.downstream) if direction == "downstream"
                              else (edge.downstream, edge.upstream))
            adjacency.setdefault(origin.key, []).append((target.key, edge))
        seen = {start.key}
        selected: dict[tuple[str, str], LineageEdge] = {}
        pending = deque([(start.key, 0)])
        depth_limited = False
        while pending:
            key, depth = pending.popleft()
            if depth >= max_depth:
                depth_limited = depth_limited or any(target not in seen for target, _ in adjacency.get(key, []))
                continue
            for target, edge in adjacency.get(key, []):
                selected[(edge.upstream.key, edge.downstream.key)] = edge
                if target not in seen:
                    if len(seen) >= max_objects:
                        raise ValueError("lineage exceeds max_objects; narrow query or raise limit")
                    seen.add(target)
                    pending.append((target, depth + 1))
        return LineageTrace(workspace_id=self.snapshot.workspace_id, document_id=self.snapshot.document_id,
                            processing_revision_id=self.snapshot.knowledge_revision.id,
                            start=start, direction=direction,
                            objects=[self.objects[key] for key in sorted(seen)],
                            edges=[selected[key] for key in sorted(selected)], depth_limited=depth_limited)
