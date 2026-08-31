"""Domain models.

This module is the single source of truth for Docgrain's data contract. It
must not import Docling, Gemini, Qwen, Qdrant, cloud SDKs or web-framework
types -- only the standard library and Pydantic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .enums import (
    AccessScope,
    JobStage,
    JobStatus,
    QualityFlag,
    SplitStrategy,
    StageStatus,
    VersionStatus,
)


class Document(BaseModel):
    id: str
    workspace_id: str
    title: str
    filename: str
    mime_type: str
    latest_version_id: str | None = None
    version_count: int = 0
    created_at: datetime
    updated_at: datetime


class DocumentVersion(BaseModel):
    id: str
    document_id: str
    workspace_id: str
    revision: int = Field(ge=1, description="1-based; never reused")
    content_sha256: str = Field(min_length=64, max_length=64)
    source_uri: str
    byte_size: int
    page_count: int = 0
    chunk_count: int = 0
    table_count: int = 0
    asset_count: int = 0
    status: VersionStatus = VersionStatus.PROCESSING
    parser: str | None = None
    vision_provider: str | None = None
    created_at: datetime
    published_at: datetime | None = None


class BoundingBox(BaseModel):
    """Page-relative box in PDF points, origin top-left."""

    x: float
    y: float
    width: float
    height: float


class Asset(BaseModel):
    id: str
    document_version_id: str
    page_number: int
    mime_type: str
    storage_uri: str
    width: int | None = None
    height: int | None = None
    byte_size: int | None = None
    sha256: str | None = None
    bbox: BoundingBox | None = None
    caption: str | None = None
    caption_is_derived: bool = Field(
        default=False,
        description="True when the caption was produced by a vision model.",
    )


class TableArtifact(BaseModel):
    id: str
    document_version_id: str
    page_number: int
    title: str | None = None
    row_count: int
    column_count: int
    confidence: float = Field(ge=0, le=1)
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    markdown: str | None = None
    html: str | None = None
    bbox: BoundingBox | None = None


class Section(BaseModel):
    id: str
    document_version_id: str
    heading: str
    level: int = Field(ge=1, le=6)
    page_numbers: list[int] = Field(default_factory=list)
    parent_id: str | None = None


class Page(BaseModel):
    id: str
    document_version_id: str
    page_number: int = Field(ge=1)
    render_uri: str
    width: int
    height: int
    dpi: int = 200
    parser: str
    confidence: float = Field(ge=0, le=1)
    char_count: int = 0
    block_count: int = 0
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    markdown: str | None = None
    structured: dict[str, Any] | None = None
    table_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    derived_content: bool = False


class Chunk(BaseModel):
    """The retrieval unit. Every field below is required by the contract."""

    id: str
    document_id: str
    document_version_id: str
    workspace_id: str
    text: str
    embedding_text: str = Field(
        description="Contextual header + text; this is what gets embedded."
    )
    heading_path: list[str]
    page_numbers: list[int]
    source_uri: str
    page_image_uris: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    access_scope: AccessScope = AccessScope.WORKSPACE
    token_count: int = 0
    split_strategy: SplitStrategy = SplitStrategy.HEADING
    derived: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _requires_provenance(self) -> Chunk:
        # Invariant 4: every chunk has at least one provenance anchor.
        if not self.page_numbers and not self.asset_ids and not self.table_ids:
            raise ValueError("chunk must carry at least one provenance anchor")
        return self


class Neighbor(BaseModel):
    chunk_id: str
    score: float = Field(ge=-1, le=1, description="Cosine similarity")
    heading_path: list[str] = Field(default_factory=list)


class BoundaryPoint(BaseModel):
    """Cosine similarity between two consecutive chunks."""

    left_chunk_id: str
    right_chunk_id: str
    score: float
    is_boundary: bool = Field(
        description="True when the score fell below the split threshold."
    )


class StageRun(BaseModel):
    stage: JobStage
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    summary: str | None = None
    provider: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    attempt: int = 0


class PageFailure(BaseModel):
    page_number: int
    stage: JobStage
    reason: str
    resolution: str | None = None


class Job(BaseModel):
    id: str
    document_id: str
    document_version_id: str
    workspace_id: str
    status: JobStatus = JobStatus.QUEUED
    stages: list[StageRun]
    page_failures: list[PageFailure] = Field(default_factory=list)
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    correlation_id: str | None = None


class DiffEntry(BaseModel):
    change: str = Field(pattern="^(added|removed|modified)$")
    target_id: str | None = None
    description: str


class VersionDiff(BaseModel):
    base_version_id: str
    head_version_id: str
    page_delta: int = 0
    chunk_delta: int = 0
    table_delta: int = 0
    asset_delta: int = 0
    entries: list[DiffEntry] = Field(default_factory=list)


class ProviderHealth(BaseModel):
    interface: str
    implementation: str
    healthy: bool
    location: str
    note: str | None = None


class Manifest(BaseModel):
    """Written once, at publish time. Immutable afterwards."""

    document_version_id: str
    status: VersionStatus
    page_count: int
    chunk_count: int
    table_count: int
    asset_count: int
    parser: str
    vision_provider: str | None = None
    embedding_model: str | None = None
    published_at: datetime
    page_failures: list[PageFailure] = Field(default_factory=list)
