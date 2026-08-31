"""Document registration and listing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

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
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import repository
from ..queue import enqueue
from ..settings import get_settings
from ..storage import get_text, object_exists, put_upload

router = APIRouter(prefix="/v1/documents", tags=["documents"])


class RegisterRequest(BaseModel):
    """A registration never carries the file body itself.

    The client asks for an upload target, PUTs the bytes to object storage and
    then confirms. The API only ever records metadata and queues a job.
    """

    workspace_id: str
    filename: str
    mime_type: str
    byte_size: int = Field(gt=0)
    source_uri: str | None = Field(
        default=None, description="Set when the bytes are already in object storage."
    )
    content_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class RegisterResponse(BaseModel):
    document: Document
    version: DocumentVersion
    job_id: str
    upload_url: str | None = None
    deduplicated: bool = Field(
        default=False,
        description="True when the hash matched an existing version; no new job was queued.",
    )


class DocumentListItem(BaseModel):
    document: Document
    latest_version: DocumentVersion | None
    latest_job_id: str | None


@router.get("", response_model=list[DocumentListItem])
def list_documents(limit: int = 50, offset: int = 0) -> list[DocumentListItem]:
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
    """Serve canonical artifacts through the API; the storage bucket remains private."""
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
    """Validate, open a version, queue a durable job -- and nothing else.

    The API must never run extraction, rendering, embedding or index writes in
    an in-process background task; it only enqueues.
    """
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
        source_uri=payload.source_uri or f"s3://docgrain/{document_id}/{version_id}/original",
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
    """Local-development upload proxy. Production storage can replace this with a direct presign."""
    version = repository.get_version(document_id, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document version not found")
    document = repository.get_document(document_id)
    if document is None or file.filename != document.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "uploaded filename does not match registration")
    object_name = f"uploads/{document_id}/{version_id}/original"
    put_upload(object_name, file.file, file.content_type or "application/octet-stream", version.byte_size)
    return {"status": "stored", "object_name": object_name}


@router.post("/{document_id}/versions/{version_id}/uploaded", status_code=status.HTTP_202_ACCEPTED)
def confirm_upload(document_id: str, version_id: str) -> dict[str, str]:
    """Confirm the direct browser upload before a worker can process it."""
    version = repository.get_version(document_id, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document version not found")
    object_name = f"uploads/{document_id}/{version_id}/original"
    if not object_exists(object_name):
        raise HTTPException(status.HTTP_409_CONFLICT, "upload has not reached object storage")
    job = repository.job_for_version(version_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if not get_settings().use_fixtures:
        enqueue(job.id)
    return {"status": "queued", "job_id": job.id}
