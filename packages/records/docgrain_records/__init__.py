"""Workspace collection discovery, verified evidence, and optional domain examples."""

from .discovery import DiscoveryClient, discover, verify_discovery
from .discovery_models import (
    WorkspaceSchema,
    collection_record_schema,
    discovery_schema,
)
from .discovery_store import accept_schema
from .extractor import build_messages, extract, verify_response
from .merge import JsonMergeStore, compare_revisions
from .merge_models import (
    AliasDecision,
    FactCandidate,
    FieldChange,
    MatchIssue,
    MergedField,
    MergeDocument,
    MergedRecord,
    MergeRevision,
    ReviewDecision,
    ReviewState,
    RevisionDiff,
    SourcePin,
    SourceRecord,
    VersionedEvidence,
)
from .model import ChatClient, ModelResponseError
from .models import (
    Activity,
    Contact,
    Evidence,
    ExtractionResult,
    Facility,
    FieldValue,
    Outlet,
    Policy,
    Property,
    RoomType,
    ServicePrice,
    hospitality_schema,
)
from .runtime import RuntimeRecords, load_runtime

__all__ = [
    "Activity",
    "AliasDecision",
    "ChatClient",
    "Contact",
    "DiscoveryClient",
    "Evidence",
    "ExtractionResult",
    "Facility",
    "FactCandidate",
    "FieldChange",
    "FieldValue",
    "JsonMergeStore",
    "MatchIssue",
    "MergeDocument",
    "MergeRevision",
    "MergedField",
    "MergedRecord",
    "ModelResponseError",
    "Outlet",
    "Policy",
    "Property",
    "ReviewDecision",
    "ReviewState",
    "RevisionDiff",
    "RoomType",
    "RuntimeRecords",
    "ServicePrice",
    "SourcePin",
    "SourceRecord",
    "VersionedEvidence",
    "WorkspaceSchema",
    "accept_schema",
    "build_messages",
    "collection_record_schema",
    "compare_revisions",
    "discover",
    "discovery_schema",
    "extract",
    "hospitality_schema",
    "load_runtime",
    "verify_discovery",
    "verify_response",
]
