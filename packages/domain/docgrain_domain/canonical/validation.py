"""Semantic checks that JSON Schema alone cannot express."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .models import (
    Annotation,
    AssetNode,
    ChartNode,
    DocumentNode,
    ListNode,
    SectionNode,
)

if TYPE_CHECKING:
    from .models import CanonicalKnowledgeSnapshot


def _unique(values: list[str], label: str) -> None:
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate {label}: {', '.join(duplicates)}")


def validate_snapshot(snapshot: CanonicalKnowledgeSnapshot) -> None:
    source = snapshot.source_version
    revision = snapshot.knowledge_revision
    if (source.document_id, source.workspace_id) != (snapshot.document_id, snapshot.workspace_id):
        raise ValueError("source document/workspace scope mismatch")
    if (revision.document_id, revision.workspace_id) != (snapshot.document_id, snapshot.workspace_id):
        raise ValueError("revision document/workspace scope mismatch")
    if revision.source_version_id != source.id:
        raise ValueError("revision source_version_id mismatch")

    nodes = {node.id: node for node in snapshot.structure}
    entities = {item.id: item for item in snapshot.entities}
    evidence = {item.id: item for item in snapshot.evidence}
    artifacts = {item.id: item for item in snapshot.artifacts}
    producers = {item.id: item for item in revision.producers}
    schemas = {item.id: item for item in snapshot.domain_schemas}
    all_ids = [
        source.id, revision.id,
        *(item.id for item in revision.producers),
        *(item.id for item in snapshot.structure),
        *(item.id for item in snapshot.entities),
        *(item.id for item in snapshot.relations),
        *(item.id for item in snapshot.records),
        *(item.id for item in snapshot.evidence),
        *(item.id for item in snapshot.artifacts),
        *(item.id for item in snapshot.domain_schemas),
    ]
    _unique(all_ids, "canonical ID across collections")
    _unique([f"{node.kind}:{node.identity_key}" for node in snapshot.structure], "node identity key")
    for collection in (snapshot.entities, snapshot.relations, snapshot.records):
        _unique([item.identity_key for item in collection], "identity key within collection")

    roots = [node for node in snapshot.structure if isinstance(node, DocumentNode)]
    if len(roots) != 1 or roots[0].id != snapshot.root_node_id:
        raise ValueError("exactly one document structural root is required")
    parents: Counter[str] = Counter()
    for node in snapshot.structure:
        if isinstance(node, (DocumentNode, SectionNode, ListNode)):
            _unique(node.children, "child reference")
            for child_id in node.children:
                if child_id not in nodes:
                    raise ValueError(f"dangling child reference: {child_id}")
                parents[child_id] += 1
        if (
            isinstance(node, (AssetNode, ChartNode))
            and node.artifact_id is not None
            and node.artifact_id not in artifacts
        ):
            raise ValueError(f"dangling artifact reference: {node.artifact_id}")
    if parents[snapshot.root_node_id]:
        raise ValueError("structural root has a parent or cycle")
    visited: set[str] = set()
    active: set[str] = set()

    def walk(node_id: str) -> None:
        if node_id in active:
            raise ValueError("structural cycle")
        if node_id in visited:
            return
        active.add(node_id)
        node = nodes[node_id]
        if isinstance(node, (DocumentNode, SectionNode, ListNode)):
            for child_id in node.children:  # Container order is reading order.
                walk(child_id)
        active.remove(node_id)
        visited.add(node_id)

    walk(snapshot.root_node_id)
    reachable_from_root = set(visited)
    for node_id in nodes:
        if node_id not in visited:
            walk(node_id)
    if len(reachable_from_root) != len(nodes):
        raise ValueError("unreachable structural node")
    if any(parents[node_id] > 1 for node_id in nodes):
        raise ValueError("more than one parent for structural node")
    if any(parents[node_id] != 1 for node_id in nodes if node_id != snapshot.root_node_id):
        raise ValueError("non-root structural node has no parent")

    for item in snapshot.evidence:
        if item.source_version_id != source.id:
            raise ValueError(f"evidence source mismatch: {item.id}")
        if item.locator.kind == "artifact_object" and item.locator.artifact_id not in artifacts:
            raise ValueError(f"dangling evidence artifact reference: {item.id}")

    def check_annotation(annotation: Annotation) -> None:
        provenance = annotation.provenance
        if provenance.producer_id not in producers:
            raise ValueError(f"dangling producer reference: {provenance.producer_id}")
        for evidence_id in provenance.evidence_ids:
            if evidence_id not in evidence:
                raise ValueError(f"dangling evidence reference: {evidence_id}")
        _unique(provenance.evidence_ids, "evidence reference")

    for item in [*snapshot.structure, *snapshot.entities, *snapshot.relations, *snapshot.records]:
        check_annotation(item.annotation)
        for field_name, annotation in item.field_annotations.items():
            if not field_name:
                raise ValueError("field annotation name must be nonempty")
            check_annotation(annotation)
    for node in snapshot.structure:
        if node.kind == "table":
            for row in node.rows:
                for cell in row:
                    if cell.annotation is not None:
                        check_annotation(cell.annotation)

    for relation in snapshot.relations:
        if relation.from_entity_id not in entities or relation.to_entity_id not in entities:
            raise ValueError(f"dangling relation endpoint: {relation.id}")
    for record in snapshot.records:
        if record.schema_id not in schemas:
            raise ValueError(f"dangling domain schema reference: {record.schema_id}")
        for entity_id in record.entity_ids:
            if entity_id not in entities:
                raise ValueError(f"dangling domain record entity reference: {entity_id}")
