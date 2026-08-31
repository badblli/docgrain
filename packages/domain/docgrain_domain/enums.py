"""Vendor-neutral enumerations shared by the API, the worker and the UI."""

from __future__ import annotations

from enum import StrEnum


class JobStage(StrEnum):
    """The ten pipeline stages, in execution order."""

    REGISTER = "register"
    RENDER = "render"
    EXTRACT = "extract"
    QUALITY = "quality"
    VISION = "vision"
    NORMALIZE = "normalize"
    CHUNK = "chunk"
    ENRICH = "enrich"
    EMBED = "embed"
    PUBLISH = "publish"


STAGE_ORDER: tuple[JobStage, ...] = tuple(JobStage)


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"


TERMINAL_JOB_STATUS: frozenset[JobStatus] = frozenset(
    {JobStatus.DONE, JobStatus.PARTIAL, JobStatus.FAILED}
)


class VersionStatus(StrEnum):
    PROCESSING = "processing"
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"


class QualityFlag(StrEnum):
    """Reasons a page may be routed to the vision provider or reported."""

    EMPTY = "empty"
    SHORT = "short"
    LOW_CONFIDENCE = "low-confidence"
    SCANNED = "scanned"
    TABLE_HEAVY = "table-heavy"
    LAYOUT_COMPLEX = "layout-complex"
    FIGURE = "figure"
    VISION_FALLBACK = "vision-fallback"


class SplitStrategy(StrEnum):
    """How a chunk came to exist. Heading-first is the primary strategy."""

    HEADING = "heading"
    TOKEN_FALLBACK = "token_fallback"
    MERGED = "merged"


class AccessScope(StrEnum):
    WORKSPACE = "workspace"
    RESTRICTED = "restricted"
    PUBLIC = "public"
