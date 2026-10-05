"""Read-only access to stored canonical knowledge revisions."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

import psycopg
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.visuals import (
    VisualInventory, VisualPreviewRequest, VisualReviewPreview, preview_visual_review, visual_inventory,
)
from fastapi import APIRouter, HTTPException, Response, status
from minio.error import S3Error
from pydantic import BaseModel

from .. import repository
from ..canonical_repository import CanonicalRepository
from ..settings import get_settings
from ..storage import storage_client

document_router = APIRouter(prefix="/v1/documents", tags=["knowledge"])
revision_router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])


class KnowledgeResponse(BaseModel):
    document_id: str
    latest_revision_id: str | None
    approved_revision_id: str | None
    snapshot: CanonicalKnowledgeSnapshot


def _store() -> CanonicalRepository:
    settings = get_settings()
    if settings.use_fixtures or not settings.canonical_persistence_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical knowledge unavailable")
    return CanonicalRepository(lambda: psycopg.connect(
        settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    ))


@document_router.get("/{document_id}/knowledge", response_model=KnowledgeResponse)
def latest_knowledge(document_id: str) -> KnowledgeResponse:
    document = repository.get_document(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    store = _store()
    heads = store.get_heads(document_id)
    if heads is None or heads[0] is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical knowledge not found")
    snapshot = store.get_snapshot(heads[0])
    if snapshot is None or (snapshot.document_id, snapshot.workspace_id,
                            snapshot.knowledge_revision.id) != (
        document_id, document.workspace_id, heads[0]
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical knowledge not found")
    return KnowledgeResponse(
        document_id=document_id,
        latest_revision_id=heads[0],
        approved_revision_id=heads[1],
        snapshot=snapshot,
    )


@revision_router.get("/revisions/{revision_id}", response_model=CanonicalKnowledgeSnapshot)
def get_revision(revision_id: str) -> CanonicalKnowledgeSnapshot:
    snapshot = _store().get_snapshot(revision_id)
    if snapshot is None or snapshot.knowledge_revision.id != revision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical revision not found")
    document = repository.get_document(snapshot.document_id)
    if document is None or document.workspace_id != snapshot.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical revision not found")
    return snapshot


@revision_router.get("/revisions/{revision_id}/visuals", response_model=VisualInventory)
def get_visual_inventory(revision_id: str) -> VisualInventory:
    return visual_inventory(get_revision(revision_id))


@revision_router.post("/revisions/{revision_id}/visuals/preview", response_model=VisualReviewPreview)
def preview_visuals(revision_id: str, request: VisualPreviewRequest) -> VisualReviewPreview:
    """Pure source-pinned preview: no write, ingestion or model call."""
    snapshot = get_revision(revision_id)
    try:
        return preview_visual_review(snapshot, request)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@revision_router.get("/revisions/{revision_id}/artifacts/{artifact_id}")
def get_revision_artifact(revision_id: str, artifact_id: str) -> Response:
    """Serve an immutable binary only when it is referenced by this revision."""
    snapshot = _store().get_snapshot(revision_id)
    if snapshot is None or snapshot.knowledge_revision.id != revision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical revision not found")
    artifact = next((item for item in snapshot.artifacts if item.id == artifact_id), None)
    if artifact is None or artifact.role != "source-image":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical artifact not found")
    parsed = urlparse(artifact.storage_uri)
    source_uri = urlparse(snapshot.source_version.storage_uri)
    settings = get_settings()
    version_ids = parse_qs(parsed.query).get("versionId", [])
    object_name = unquote(parsed.path.lstrip("/"))
    source_parts = source_uri.path.lstrip("/").split("/")
    if (source_uri.scheme != "s3" or source_uri.netloc != settings.s3_bucket or len(source_parts) != 4
            or source_parts[0] != "uploads" or source_parts[1] != snapshot.document_id
            or source_parts[3] != "original"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical artifact not found")
    expected_prefix = f"artifacts/{snapshot.document_id}/{source_parts[2]}/structural/assets/"
    if parsed.scheme != "s3" or parsed.netloc != settings.s3_bucket or not object_name.startswith(expected_prefix) or not version_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical artifact not found")
    try:
        stored = storage_client().get_object(settings.s3_bucket, object_name, version_id=version_ids[0])
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchVersion", "NoSuchBucket"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "canonical artifact not found") from exc
        raise
    try:
        body = stored.read()
    finally:
        stored.close()
        stored.release_conn()
    return Response(body, media_type=artifact.mime_type,
                    headers={"Cache-Control": "private, max-age=31536000, immutable"})
