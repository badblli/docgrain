"""Document registration and listing."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from typing import Annotated
from urllib.parse import urlparse

from docgrain_domain import (
    STAGE_ORDER,
    Document,
    DocumentVersion,
    Job,
    JobStatus,
    StageRun,
    StageStatus,
    VersionStatus,
    new_id,
)
from docgrain_domain.docling_formats import DOCLING_VERSION, SPECS
from docgrain_domain.source_format import (
    CorruptSource,
    FormatMismatch,
    SourceFormat,
    declared_format,
    missing_requirements,
    resolve_format,
    verify_format,
)
from docgrain_domain.storage_paths import upload_key
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import format_capabilities, repository
from ..queue import enqueue
from ..settings import get_settings
from ..storage import get_text, object_exists, put_upload
from .workspace_settings import router as settings_router

router = APIRouter(prefix="/v1/documents", tags=["documents"])
workspaces_router = APIRouter(tags=["workspaces"])
workspaces_router.include_router(settings_router)


def _require_live_uploads() -> None:
    if get_settings().use_fixtures:
        raise HTTPException(status.HTTP_409_CONFLICT, "demo mode is read-only; uploads are disabled")


class WorkspaceListItem(BaseModel):
    id: str
    name: str
    documents: int


class FormatItem(BaseModel):
    format: str
    extensions: list[str]
    enabled: bool
    missing: list[str]


class FormatList(BaseModel):
    docling_version: str
    formats: list[FormatItem]


@workspaces_router.get("/v1/formats", response_model=FormatList)
def list_formats() -> FormatList:
    """Accepted file types and whether this installation can read them now (WP106)."""
    available = format_capabilities.available()
    items = []
    for spec in SPECS.values():
        missing = missing_requirements(SourceFormat(spec.value), available) if spec.requirements else []
        items.append(FormatItem(format=spec.value, extensions=list(spec.extensions),
                                enabled=not missing, missing=missing))
    return FormatList(docling_version=DOCLING_VERSION, formats=items)


@workspaces_router.get("/v1/workspaces", response_model=list[WorkspaceListItem])
def list_workspaces() -> list[WorkspaceListItem]:
    return [
        WorkspaceListItem(id=str(item["id"]), name=str(item.get("name", item["id"])),
                          documents=int(item["documents"]))
        for item in repository.list_workspaces()
    ]


class RegisterRequest(BaseModel):
    """A registration never carries the file body itself.

    The client uploads through the API proxy and then confirms. Registration
    records metadata; only confirmation enqueues work.
    """

    workspace_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    filename: str
    mime_type: str
    byte_size: int = Field(gt=0)
    source_uri: str | None = Field(
        default=None, description="Reserved; external source ingestion is not implemented."
    )
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RegisterResponse(BaseModel):
    document: Document
    version: DocumentVersion
    job_id: str
    upload_url: str | None = None
    deduplicated: bool = Field(
        default=False,
        description="An existing version with the same workspace and content SHA-256 was reused.",
    )


class DocumentListItem(BaseModel):
    document: Document
    latest_version: DocumentVersion | None
    latest_job_id: str | None


@router.get("", response_model=list[DocumentListItem])
def list_documents(limit: int = 50, offset: int = 0, workspace_id: str | None = None) -> list[DocumentListItem]:
    versions = repository.versions_by_id()
    items = [
        DocumentListItem(
            document=document,
            latest_version=versions.get(document.latest_version_id or ""),
            latest_job_id=next(
                (job.id for job in repository.jobs_for_document(document.id)), None
            ),
        )
        for document in repository.list_documents()
        if workspace_id is None or document.workspace_id == workspace_id
    ]
    return items[offset : offset + limit]


@router.get("/{document_id}", response_model=DocumentListItem)
def get_document(document_id: str) -> DocumentListItem:
    document = repository.get_document(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    versions = repository.versions_by_id()
    return DocumentListItem(
        document=document,
        latest_version=versions.get(document.latest_version_id or ""),
        latest_job_id=next(
            (job.id for job in repository.jobs_for_document(document.id)), None
        ),
    )


@router.get("/{document_id}/versions", response_model=list[DocumentVersion])
def list_versions(document_id: str) -> list[DocumentVersion]:
    return repository.list_versions(document_id)


@router.get("/{document_id}/versions/{version_id}/artifacts/{artifact_name}")
def get_artifact(document_id: str, version_id: str, artifact_name: str) -> PlainTextResponse:
    """Serve provider-specific extraction artifacts, not canonical knowledge."""
    if get_settings().use_fixtures:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demo has no stored extraction artifacts")
    if artifact_name not in {"document.md", "document.json"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not found")
    if repository.get_version(document_id, version_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document version not found")
    content = get_text(f"artifacts/{document_id}/{version_id}/{artifact_name}")
    if content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact is not available yet")
    media_type = "text/markdown; charset=utf-8" if artifact_name.endswith(".md") else "application/json"
    return PlainTextResponse(content, media_type=media_type)


@router.post("", response_model=RegisterResponse, status_code=status.HTTP_202_ACCEPTED)
def register_document(payload: RegisterRequest) -> RegisterResponse:
    """Register a supported document/version; confirmation enqueues the job."""
    _require_live_uploads()
    with repository.registration_lock(payload.workspace_id, payload.content_sha256):
        return _register_document(payload)


def _register_document(payload: RegisterRequest) -> RegisterResponse:
    if payload.source_uri is not None:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "external source ingestion is not implemented")
    try:
        # KULLANILMIYOR (karar 18): declared_format(payload.filename, payload.mime_type)
        # WP106: Docling can read the format, but its reader may need something this installation lacks.
        format_capabilities.ensure_format_enabled(declared_format(payload.filename, payload.mime_type))
    except FormatMismatch as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    if payload.content_sha256:
        for existing in repository.list_versions():
            if (existing.workspace_id == payload.workspace_id
                    and existing.content_sha256 == payload.content_sha256):
                document = repository.get_document(existing.document_id)
                job = repository.job_for_version(existing.id)
                if document is not None and job is not None:
                    object_name = urlparse(existing.source_uri).path.lstrip("/")
                    return RegisterResponse(
                        document=document, version=existing, job_id=job.id, deduplicated=True,
                        upload_url=(None if object_exists(object_name) else
                                    f"{get_settings().api_public_url}/v1/documents/{document.id}"
                                    f"/versions/{existing.id}/content"),
                    )
    now = datetime.now(UTC)
    document_id = new_id("document")
    version_id = new_id("version")
    document = Document(
        id=document_id,
        workspace_id=payload.workspace_id,
        title=payload.filename.rsplit(".", 1)[0],
        filename=payload.filename,
        mime_type=payload.mime_type,
        latest_version_id=version_id,
        version_count=1,
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        workspace_id=payload.workspace_id,
        revision=1,
        content_sha256=payload.content_sha256 or ("0" * 64),
        source_uri=f"s3://{get_settings().s3_bucket}/{upload_key(payload.workspace_id, document_id, version_id)}",
        byte_size=payload.byte_size,
        status=VersionStatus.PROCESSING,
        created_at=now,
    )
    job = Job(
        id=new_id("job"),
        document_id=document_id,
        document_version_id=version_id,
        workspace_id=payload.workspace_id,
        status=JobStatus.QUEUED,
        stages=[
            StageRun(
                stage=stage,
                status=StageStatus.PENDING,
                attempt=0,
            )
            for stage in STAGE_ORDER
        ],
        queued_at=now,
    )
    repository.add(document, version, job)
    return RegisterResponse(
        document=document,
        version=version,
        job_id=job.id,
        upload_url=(
            None
            if payload.source_uri
            else f"{get_settings().api_public_url}/v1/documents/{document_id}/versions/{version_id}/content"
        ),
    )


@router.put("/{document_id}/versions/{version_id}/content", status_code=status.HTTP_201_CREATED)
def upload_content(
    document_id: str,
    version_id: str,
    file: Annotated[UploadFile, File(...)],
) -> dict[str, str]:
    """Local-development upload proxy; signed uploads are not wired in."""
    _require_live_uploads()
    version = repository.get_version(document_id, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document version not found")
    document = repository.get_document(document_id)
    if document is None or file.filename != document.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "uploaded filename does not match registration")
    try:
        source_format = declared_format(document.filename, document.mime_type)
        if file.content_type:
            declared_format(document.filename, file.content_type)
        data = file.file.read()
        if len(data) != version.byte_size:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "upload size differs from registration")
        verify_format(data, source_format)
        # WP106: an ".xml" file is only known as USPTO/JATS/XBRL/DocLang once its content is read.
        format_capabilities.ensure_format_enabled(resolve_format(data, source_format))
    except FormatMismatch as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except CorruptSource as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if version.content_sha256 != "0" * 64 and sha256(data).hexdigest() != version.content_sha256:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "upload checksum differs from registration")
    object_name = urlparse(version.source_uri).path.lstrip("/")
    put_upload(object_name, BytesIO(data), file.content_type or "application/octet-stream", len(data))
    return {"status": "stored", "object_name": object_name}


@router.post("/{document_id}/versions/{version_id}/uploaded", status_code=status.HTTP_202_ACCEPTED)
def confirm_upload(document_id: str, version_id: str) -> dict[str, str]:
    """Check the uploaded object exists and dispatch its job."""
    _require_live_uploads()
    version = repository.get_version(document_id, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document version not found")
    object_name = urlparse(version.source_uri).path.lstrip("/")
    if not object_exists(object_name):
        raise HTTPException(status.HTTP_409_CONFLICT, "upload has not reached object storage")
    job = repository.job_for_version(version_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    enqueue(job.id)
    return {"status": "queued", "job_id": job.id}
