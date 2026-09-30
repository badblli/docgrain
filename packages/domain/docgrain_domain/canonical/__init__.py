"""Versioned canonical knowledge and lifecycle public contracts."""

from .identity import (
    IDENTITY_POLICY_VERSION,
    canonical_json_bytes,
    deterministic_item_id,
    new_canonical_id,
)
from .lifecycle import (
    DerivedRevision,
    ProcessingSpec,
    chunk_id,
    entity_id,
    logical_document_id,
    processing_revision_id,
    source_revision_id,
)
from .lineage import DerivedManifest, LineageEdge, LineageGraph, LineageTrace, ObjectRef
from .locations import (
    ArtifactObjectLocator,
    DocxBlockLocator,
    NormalizedBox,
    PdfPageLocator,
    SpreadsheetRangeLocator,
    TextSpanLocator,
)
from .models import (
    Annotation,
    ArtifactRef,
    AssetNode,
    CanonicalKnowledgeSnapshot,
    ChartNode,
    DateRange,
    DatetimeRange,
    DocumentNode,
    DomainRecord,
    DomainSchemaRef,
    DomainValidationResult,
    Entity,
    Evidence,
    KnowledgeRevision,
    ListNode,
    Producer,
    Provenance,
    Relation,
    SectionNode,
    SourceVersion,
    TableCell,
    TableNode,
    TextBlock,
)
from .validation import validate_snapshot


def canonical_export_path(document_id: str, knowledge_revision_id: str) -> str:
    """Reserved M4 publication path; M1 does not write this artifact."""
    return f"documents/{document_id}/knowledge/{knowledge_revision_id}/canonical.json"


__all__ = [
    "IDENTITY_POLICY_VERSION",
    "Annotation",
    "ArtifactObjectLocator",
    "ArtifactRef",
    "AssetNode",
    "CanonicalKnowledgeSnapshot",
    "ChartNode",
    "DateRange",
    "DatetimeRange",
    "DerivedManifest",
    "DerivedRevision",
    "DocumentNode",
    "DocxBlockLocator",
    "DomainRecord",
    "DomainSchemaRef",
    "DomainValidationResult",
    "Entity",
    "Evidence",
    "KnowledgeRevision",
    "LineageEdge",
    "LineageGraph",
    "LineageTrace",
    "ListNode",
    "NormalizedBox",
    "ObjectRef",
    "PdfPageLocator",
    "ProcessingSpec",
    "Producer",
    "Provenance",
    "Relation",
    "SectionNode",
    "SourceVersion",
    "SpreadsheetRangeLocator",
    "TableCell",
    "TableNode",
    "TextBlock",
    "TextSpanLocator",
    "canonical_export_path",
    "canonical_json_bytes",
    "chunk_id",
    "deterministic_item_id",
    "entity_id",
    "logical_document_id",
    "new_canonical_id",
    "processing_revision_id",
    "source_revision_id",
    "validate_snapshot",
]
