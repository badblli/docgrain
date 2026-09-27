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
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    return version


def _fixture_version(version_id: str) -> bool:
    return get_settings().use_fixtures and any(
        version.id == version_id for version in fixtures.VERSIONS
    )


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
        confidence=None,
        quality_flags=[],
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
    if get_settings().use_fixtures:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demo pages have no stored renders")
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
    """Simulated boundary scores, available only for demo fixtures."""
    _require_version(version_id)
    if not _fixture_version(version_id):
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "chunk boundary analysis is not implemented")
    return BoundaryReport(threshold=fixtures.SPLIT_THRESHOLD, points=fixtures.boundaries())


@router.get("/{version_id}/diff", response_model=VersionDiff)
def diff(version_id: str, base: str) -> VersionDiff:
    """Live responses contain count deltas only, not semantic changes."""
    head = _require_version(version_id)
    base_version = _require_version(base)
    if head.document_id != base_version.document_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "versions must belong to the same document")
    if _fixture_version(version_id) and version_id == fixtures.V2 and base == fixtures.V1:
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


@router.post("/{version_id}/retry", response_model=RetryResponse, status_code=status.HTTP_501_NOT_IMPLEMENTED)
def retry(version_id: str, payload: RetryRequest) -> RetryResponse:
    """Reserved endpoint. No retry is scheduled in either mode."""
    _require_version(version_id)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "stage retry is not implemented; no work was queued")
