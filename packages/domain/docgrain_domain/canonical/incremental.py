"""Exact canonical diffs, complete lineage invalidation and chunk reuse planning."""

from __future__ import annotations

from typing import Literal

from .chunking import ChunkingSpec, derive_chunk_set
from .identity import canonical_json_bytes
from .lineage import LineageGraph, ObjectRef
from .locations import StrictModel
from .models import CanonicalKnowledgeSnapshot

COLLECTIONS = ("structure", "entities", "relations", "records", "artifacts")


class ObjectChange(StrictModel):
    collection: str
    object_id: str
    operation: Literal["added", "removed", "modified"]
    content_paths: list[str]
    metadata_paths: list[str]


class CanonicalDiff(StrictModel):
    workspace_id: str
    document_id: str
    from_revision_id: str
    to_revision_id: str
    source_changed: bool
    changes: list[ObjectChange]


def _paths(a, b, path=""):
    if canonical_json_bytes(a) == canonical_json_bytes(b):
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        result = []
        for key in sorted(a.keys() | b.keys()):
            child = path + "/" + key.replace("~", "~0").replace("/", "~1")
            result.extend(_paths(a[key], b[key], child) if key in a and key in b else [child])
        return result
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [p for i, (left, right) in enumerate(zip(a, b, strict=True))
                for p in _paths(left, right, path + f"/{i}")]
    return [path or "/"]


def _split(value):
    """Annotations anywhere in rows/entities belong to metadata, not embedding text."""
    if isinstance(value, dict):
        content, metadata = {}, {}
        for key, child in value.items():
            if key in {"annotation", "field_annotations", "review_history"}:
                metadata[key] = child
            else:
                c, m = _split(child)
                content[key] = c
                if m:
                    metadata[key] = m
        return content, metadata
    if isinstance(value, list):
        pairs = [_split(child) for child in value]
        return [c for c, _ in pairs], [m for _, m in pairs] if any(m for _, m in pairs) else {}
    return value, {}


def canonical_diff(old: CanonicalKnowledgeSnapshot, new: CanonicalKnowledgeSnapshot) -> CanonicalDiff:
    old = CanonicalKnowledgeSnapshot.model_validate(old.model_dump(mode="json"))
    new = CanonicalKnowledgeSnapshot.model_validate(new.model_dump(mode="json"))
    if (old.workspace_id, old.document_id) != (new.workspace_id, new.document_id):
        raise ValueError("canonical diff workspace/document scope mismatch")
    old_evidence = {e.id: e.model_dump(mode="json") for e in old.evidence}
    new_evidence = {e.id: e.model_dump(mode="json") for e in new.evidence}
    changed_evidence = {key for key in old_evidence.keys() | new_evidence.keys()
                        if old_evidence.get(key) != new_evidence.get(key)}
    changes = []
    for collection in COLLECTIONS:
        left = {obj.id: obj.model_dump(mode="json") for obj in getattr(old, collection)}
        right = {obj.id: obj.model_dump(mode="json") for obj in getattr(new, collection)}
        for key in sorted(left.keys() | right.keys()):
            if key not in left or key not in right:
                changes.append(ObjectChange(collection=collection, object_id=key,
                                             operation="added" if key in right else "removed",
                                             content_paths=["/"], metadata_paths=[]))
                continue
            a, ma = _split(left[key])
            b, mb = _split(right[key])
            content, metadata = _paths(a, b), _paths(ma, mb)
            def evidence_refs(value):
                if isinstance(value, dict):
                    return set(value.get("evidence_ids", [])) | set().union(*(evidence_refs(v) for v in value.values()))
                if isinstance(value, list):
                    return set().union(*(evidence_refs(v) for v in value))
                return set()
            if changed_evidence & (evidence_refs(ma) | evidence_refs(mb)):
                metadata.append("/evidence")
            if content or metadata:
                changes.append(ObjectChange(collection=collection, object_id=key, operation="modified",
                                             content_paths=content, metadata_paths=metadata))
    return CanonicalDiff(workspace_id=new.workspace_id, document_id=new.document_id,
                         from_revision_id=old.knowledge_revision.id, to_revision_id=new.knowledge_revision.id,
                         source_changed=old.source_version != new.source_version, changes=changes)


def invalidated_descendants(diff: CanonicalDiff, graph: LineageGraph) -> list[ObjectRef]:
    if (diff.workspace_id, diff.document_id, diff.from_revision_id) != (
        graph.snapshot.workspace_id, graph.snapshot.document_id, graph.snapshot.knowledge_revision.id
    ):
        raise ValueError("diff/lineage scope mismatch")
    pending = {ObjectRef(kind="canonical", revision_id=diff.from_revision_id, object_id=c.object_id).key
               for c in diff.changes if c.operation != "added"}
    reached = set(pending)
    while pending:
        downstream = {e.downstream.key for e in graph.edges if e.upstream.key in pending} - reached
        reached.update(downstream)
        pending = downstream
    return sorted((graph.objects[key] for key in reached if key in graph.objects),
                  key=lambda ref: (ref.kind, ref.revision_id, ref.object_id))


class ChunkPlan(StrictModel):
    reuse: list[str]
    embed: list[str]
    delete: list[str]
    metadata_refresh: list[str]


def plan_chunks(old: CanonicalKnowledgeSnapshot, new: CanonicalKnowledgeSnapshot,
                spec: ChunkingSpec, *, previous_spec: ChunkingSpec | None = None) -> ChunkPlan:
    canonical_diff(old, new)  # Validate scope before any reuse.
    before = {c.object_ref.object_id: c for c in derive_chunk_set(old, previous_spec or spec).chunks}
    after = {c.object_ref.object_id: c for c in derive_chunk_set(new, spec).chunks}
    reuse = [key for key, chunk in after.items() if key in before
             and before[key].content_sha256 == chunk.content_sha256]
    return ChunkPlan(reuse=reuse, embed=[key for key in after if key not in reuse],
                     delete=[key for key in before if key not in after],
                     metadata_refresh=[key for key in reuse if before[key] != after[key]])
