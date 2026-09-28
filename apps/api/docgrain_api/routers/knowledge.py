"""Read-only access to stored canonical knowledge revisions."""

from __future__ import annotations

import psycopg
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from .. import repository
from ..canonical_repository import CanonicalRepository
from ..settings import get_settings

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
