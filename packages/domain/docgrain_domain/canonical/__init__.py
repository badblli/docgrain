"""Canonical knowledge v0.1 public contract. Legacy domain models remain separate."""

from .identity import (
    IDENTITY_POLICY_VERSION,
    canonical_json_bytes,
    deterministic_item_id,
    new_canonical_id,
)
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
    "IDENTITY_POLICY_VERSION", "Annotation", "ArtifactObjectLocator", "ArtifactRef", "AssetNode",
    "CanonicalKnowledgeSnapshot", "ChartNode", "DateRange", "DatetimeRange", "DocumentNode",
    "DocxBlockLocator", "DomainRecord", "DomainSchemaRef", "DomainValidationResult", "Entity",
    "Evidence", "KnowledgeRevision", "ListNode", "NormalizedBox", "PdfPageLocator", "Producer",
    "Provenance", "Relation", "SectionNode", "SourceVersion", "SpreadsheetRangeLocator",
    "TableCell", "TableNode", "TextBlock", "TextSpanLocator", "canonical_export_path", "canonical_json_bytes",
    "deterministic_item_id", "new_canonical_id", "validate_snapshot",
]
