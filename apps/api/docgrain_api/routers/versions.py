"""Version artifacts: pages, tables, assets, chunks, diff and retry."""

from __future__ import annotations

import json

from docgrain_domain import (
    Asset,
    BoundaryPoint,
    Chunk,
    DocumentVersion,
    JobStage,
    Page,
    TableArtifact,
)
from docgrain_domain.models import VersionDiff
from docgrain_domain.state import retryable_stages
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from .. import fixtures, repository
from ..settings import get_settings
from ..storage import get_text, storage_client

router = APIRouter(prefix="/v1/versions", tags=["versions"])


def _require_version(version_id: str) -> DocumentVersion:
    version = next(
        (v for v in repository.list_versions() if v.id == version_id),
        None,
    ) or next((v for v in fixtures.VERSIONS if v.id == version_id), None)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    return version


def _fixture_version(version_id: str) -> bool:
    return any(version.id == version_id for version in fixtures.VERSIONS)


def _page_manifest(version: DocumentVersion) -> dict[int, dict[str, int]]:
    content = get_text(
        f"artifacts/{version.document_id}/{version.id}/pages.json"
    )
    if not content:
        return {}
    try:
        payload = json.loads(content)
        return {
            int(page["page_number"]): page
            for page in payload.get("pages", [])
            if isinstance(page, dict) and "page_number" in page
        }
    except (TypeError, ValueError, KeyError):
        return {}


def _live_page(
    version: DocumentVersion,
    page_number: int,
    manifest: dict[int, dict[str, int]] | None = None,
) -> Page:
    if page_number < 1 or page_number > version.page_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "page not found")
    job = repository.job_for_version(version.id)
    extraction_failed = any(
        failure.page_number == page_number
        for failure in (job.page_failures if job else [])
    )
    metadata = (manifest if manifest is not None else _page_manifest(version)).get(
        page_number, {}
    )
    return Page(
        id=f"pg_{version.id}_{page_number:04d}",
        document_version_id=version.id,
        page_number=page_number,
        render_uri=(
            f"{get_settings().api_public_url}/v1/versions/{version.id}/pages/"
            f"{page_number}/render"
        ),
        width=int(metadata.get("width", 1654)),
        height=int(metadata.get("height", 2339)),
        dpi=200,
        parser=version.parser or "docling",
        confidence=0.0 if extraction_failed else 1.0,
        quality_flags=["empty"] if extraction_failed else [],
    )


@router.get("/{version_id}", response_model=DocumentVersion)
def get_version(version_id: str) -> DocumentVersion:
    return _require_version(version_id)


@router.get("/{version_id}/pages", response_model=list[Page])
def list_pages(version_id: str) -> list[Page]:
    version = _require_version(version_id)
    if _fixture_version(version_id):
        return [page for page in fixtures.PAGES if page.document_version_id == version_id]
    manifest = _page_manifest(version)
    return [
        _live_page(version, number, manifest)
        for number in range(1, version.page_count + 1)
    ]


@router.get("/{version_id}/pages/{page_number}", response_model=Page)
def get_page(version_id: str, page_number: int) -> Page:
    version = _require_version(version_id)
    if not _fixture_version(version_id):
        return _live_page(version, page_number)
    page = next(
        (
            p
            for p in fixtures.PAGES
            if p.document_version_id == version_id and p.page_number == page_number
        ),
        None,
    )
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "page not found")
    # Provenance links are resolved at read time so the console never has to
    # join across endpoints.
    page = page.model_copy(
        update={
            "table_ids": [t.id for t in fixtures.TABLES if t.page_number == page_number],
            "asset_ids": [a.id for a in fixtures.ASSETS if a.page_number == page_number],
            "chunk_ids": [c.id for c in fixtures.CHUNKS if page_number in c.page_numbers],
        }
    )
    return page


@router.get("/{version_id}/pages/{page_number}/render", response_class=Response)
def get_page_render(version_id: str, page_number: int) -> Response:
    version = _require_version(version_id)
    _live_page(version, page_number)
    document = repository.get_document(version.document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    object_name = f"artifacts/{document.id}/{version.id}/pages/{page_number:04d}.png"
    try:
        stored = storage_client().get_object(get_settings().s3_bucket, object_name)
    except Exception as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "page render not found") from exc
    try:
        content = stored.read()
    finally:
        stored.close()
        stored.release_conn()
    return Response(content=content, media_type="image/png")


@router.get("/{version_id}/tables", response_model=list[TableArtifact])
def list_tables(version_id: str) -> list[TableArtifact]:
    _require_version(version_id)
    if not _fixture_version(version_id):
        return []
    return [t for t in fixtures.TABLES if t.document_version_id == version_id]


@router.get("/{version_id}/assets", response_model=list[Asset])
def list_assets(version_id: str) -> list[Asset]:
    _require_version(version_id)
    if not _fixture_version(version_id):
        return []
    return [a for a in fixtures.ASSETS if a.document_version_id == version_id]


@router.get("/{version_id}/chunks", response_model=list[Chunk])
def list_chunks(version_id: str) -> list[Chunk]:
    _require_version(version_id)
    if not _fixture_version(version_id):
        return []
    return [c for c in fixtures.CHUNKS if c.document_version_id == version_id]


class BoundaryReport(BaseModel):
    threshold: float
    points: list[BoundaryPoint]


@router.get("/{version_id}/chunks/boundaries", response_model=BoundaryReport)
def chunk_boundaries(version_id: str) -> BoundaryReport:
    """Consecutive-chunk cosine similarity.

    Docgrain splits by heading first; this report exists to *audit* that
    decision, not to make it. A dip below the threshold that lines up with a
    heading confirms the split; a dip in the middle of high similarity means
    the chunk was cut unnecessarily and should be merged.
    """
    _require_version(version_id)
    if not _fixture_version(version_id):
        return BoundaryReport(threshold=fixtures.SPLIT_THRESHOLD, points=[])
    return BoundaryReport(threshold=fixtures.SPLIT_THRESHOLD, points=fixtures.boundaries())


@router.get("/{version_id}/diff", response_model=VersionDiff)
def diff(version_id: str, base: str) -> VersionDiff:
    head = _require_version(version_id)
    base_version = _require_version(base)
    if _fixture_version(version_id) and _fixture_version(base):
        return fixtures.DIFF
    return VersionDiff(
        base_version_id=base_version.id,
        head_version_id=head.id,
        page_delta=head.page_count - base_version.page_count,
        chunk_delta=head.chunk_count - base_version.chunk_count,
        table_delta=head.table_count - base_version.table_count,
        asset_delta=head.asset_count - base_version.asset_count,
    )


class RetryRequest(BaseModel):
    from_stage: JobStage


class RetryResponse(BaseModel):
    job_id: str
    replays: list[JobStage]


@router.post("/{version_id}/retry", response_model=RetryResponse, status_code=status.HTTP_202_ACCEPTED)
def retry(version_id: str, payload: RetryRequest) -> RetryResponse:
    """Re-run from a stage. Stages are idempotent, so a replay is safe."""
    _require_version(version_id)
    job = repository.job_for_version(version_id) or next(
        (j for j in fixtures.JOBS if j.document_version_id == version_id),
        None,
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no job for this version")
    statuses = {run.stage: run.status for run in job.stages}
    replays = retryable_stages(statuses) or [payload.from_stage]
    return RetryResponse(job_id=job.id, replays=replays)
