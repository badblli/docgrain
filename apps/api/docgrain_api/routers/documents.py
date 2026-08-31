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
from pydantic import BaseModel, Field

from .. import repository
from ..settings import get_settings
from ..storage import object_exists, put_upload

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
    document = next((d for d in repository.documents if d.id == document_id), None)
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
    return [v for v in repository.versions if v.document_id == document_id]


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
    version = next(
        (item for item in repository.versions if item.id == version_id and item.document_id == document_id),
        None,
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document version not found")
    if file.filename != next(item.filename for item in repository.documents if item.id == document_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "uploaded filename does not match registration")
    object_name = f"uploads/{document_id}/{version_id}/original"
    put_upload(object_name, file.file, file.content_type or "application/octet-stream", version.byte_size)
    return {"status": "stored", "object_name": object_name}


@router.post("/{document_id}/versions/{version_id}/uploaded", status_code=status.HTTP_202_ACCEPTED)
def confirm_upload(document_id: str, version_id: str) -> dict[str, str]:
    """Confirm the direct browser upload before a worker can process it."""
    version = next(
        (item for item in repository.versions if item.id == version_id and item.document_id == document_id),
        None,
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document version not found")
    object_name = f"uploads/{document_id}/{version_id}/original"
    if not object_exists(object_name):
        raise HTTPException(status.HTTP_409_CONFLICT, "upload has not reached object storage")
    return {"status": "queued", "job_id": next(job.id for job in repository.jobs if job.document_version_id == version_id)}
