"""End-user source reading, bounded typed edits and immutable review revisions."""

from datetime import datetime
from urllib.parse import quote

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.lifecycle import digest
from docgrain_domain.canonical.locations import StrictModel
from docgrain_domain.canonical.review import (
    ReviewField,
    ReviewPreview,
    ReviewRequest,
    SaveReviewRequest,
    preview_review,
    review_fields,
)
from docgrain_domain.storage_paths import source_version_id
from fastapi import APIRouter, HTTPException, Response
from minio.error import S3Error

from .. import repository as metadata
from ..canonical_repository import CanonicalConflict
from ..review_publication import StorageIntegrityError, save_review, verified_source
from ..settings import get_settings
from ..storage import storage_client
from . import knowledge

router = APIRouter(prefix="/v1", tags=["review"])


class ReviewHistoryItem(StrictModel):
    revision_id: str
    parent_revision_id: str | None
    created_at: datetime
    kind: str
    reviewer_id: str | None
    reason: str | None


class SourcePage(StrictModel):
    page_number: int
    render_url: str


class ReviewSource(StrictModel):
    filename: str
    mime_type: str
    download_url: str
    document_version_id: str | None
    pages: list[SourcePage]


class ReviewWorkspace(StrictModel):
    document_id: str
    latest_revision_id: str
    approved_revision_id: str | None
    snapshot_sha256: str
    can_edit: bool
    snapshot: CanonicalKnowledgeSnapshot
    source: ReviewSource
    fields: list[ReviewField]
    history: list[ReviewHistoryItem]
    warnings: list[str]


def _base(document_id, revision_id=None):
    document = metadata.get_document(document_id)
    if document is None:
        raise HTTPException(404, "document not found")
    store = knowledge._store()
    heads = store.get_heads(document_id)
    if heads is None or heads[0] is None:
        raise HTTPException(404, "canonical knowledge not found")
    selected = revision_id or heads[0]
    snapshot = store.get_snapshot(selected)
    if snapshot is None or (
        snapshot.document_id, snapshot.workspace_id, snapshot.knowledge_revision.id
    ) != (document_id, document.workspace_id, selected):
        raise HTTPException(404, "revision not found in document/workspace")
    return store, snapshot, heads


@router.get("/documents/{document_id}/review", response_model=ReviewWorkspace)
def get_workspace(document_id: str, revision_id: str | None = None):
    store, snapshot, heads = _base(document_id, revision_id)
    base_url = get_settings().api_public_url.rstrip("/")
    source = snapshot.source_version
    version_id = source_version_id(source.storage_uri, snapshot.workspace_id, document_id)
    version = metadata.get_version(document_id, version_id) if version_id else None
    pages = []
    if version is None or version.content_sha256 != source.content_sha256:
        version_id = None
    elif source.mime_type == "application/pdf":
        pages = [SourcePage(page_number=n, render_url=f"{base_url}/v1/versions/{version.id}/pages/{n}/render")
                 for n in range(1, version.page_count + 1)]
    fields = review_fields(snapshot)
    warnings = [
        "Alan düzenlemek, belgenin bütün anlamını doğrulamak değildir. Açık eksikler korunur.",
        "Formüller, kaynak dosyası ve geometri değiştirilemez. Embedding üretilmez.",
    ]
    if snapshot.knowledge_revision.id != heads[0]:
        warnings.append("Geçmiş revision salt okunur. Düzenlemek için güncel revision'a dönün.")
    return ReviewWorkspace(
        document_id=document_id, latest_revision_id=heads[0], approved_revision_id=heads[1],
        snapshot_sha256=digest(snapshot.model_dump(mode="json")),
        can_edit=snapshot.knowledge_revision.id == heads[0] and any(f.editable for f in fields),
        snapshot=snapshot, fields=fields, history=store.review_history(document_id),
        source=ReviewSource(filename=source.filename, mime_type=source.mime_type,
                            download_url=f"{base_url}/v1/knowledge/revisions/{snapshot.knowledge_revision.id}/source",
                            document_version_id=version_id, pages=pages), warnings=warnings,
    )


@router.post("/documents/{document_id}/reviews/preview", response_model=ReviewPreview)
def get_review_preview(document_id: str, request: ReviewRequest):
    _, base, heads = _base(document_id, request.base_revision_id)
    if heads[0] != request.base_revision_id:
        raise HTTPException(409, "latest revision changed; reload document")
    try:
        return preview_review(base, request)
    except ValueError as exc:
        code = 409 if any(word in str(exc).lower() for word in ("stale", "snapshot", "base revision", "before", "review base belongs")) else 422
        raise HTTPException(code, str(exc)) from exc


@router.post("/documents/{document_id}/reviews")
def commit_review(document_id: str, request: SaveReviewRequest):
    if get_settings().use_fixtures:
        raise HTTPException(409, "demo mode is read-only")
    store, base, _ = _base(document_id, request.base_revision_id)
    try:
        snapshot, inserted = save_review(store, base, request, storage_client(), get_settings().s3_bucket)
    except CanonicalConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except StorageIntegrityError as exc:
        raise HTTPException(503, "source/output integrity verification failed; no revision committed") from exc
    except ValueError as exc:
        code = 409 if any(word in str(exc).lower() for word in ("stale", "review base belongs")) else 422
        raise HTTPException(code, str(exc)) from exc
    except (S3Error, OSError) as exc:
        raise HTTPException(503, "source/output storage unavailable; no revision committed") from exc
    heads = store.get_heads(document_id)
    return {"revision_id": snapshot.knowledge_revision.id, "parent_revision_id": base.knowledge_revision.id,
            "inserted": inserted, "latest_revision_id": heads[0], "approved_revision_id": heads[1],
            "output_published": True}


@router.get("/knowledge/revisions/{revision_id}/source")
def get_original_source(revision_id: str):
    snapshot = knowledge.get_revision(revision_id)
    try:
        data = verified_source(storage_client(), get_settings().s3_bucket, snapshot)
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchVersion", "NoSuchBucket"}:
            raise HTTPException(404, "original source version unavailable") from exc
        raise HTTPException(503, "source storage unavailable") from exc
    except ValueError as exc:
        raise HTTPException(503, "original source checksum or scope verification failed") from exc
    return Response(data, media_type=snapshot.source_version.mime_type,
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(snapshot.source_version.filename, safe=""),
                             "Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})
