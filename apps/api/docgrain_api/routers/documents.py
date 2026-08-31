"""Document registration and listing."""

from __future__ import annotations

from datetime import UTC, datetime

from docgrain_domain import Document, DocumentVersion, VersionStatus, new_id
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from .. import fixtures
from ..settings import get_settings

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
    versions = {version.id: version for version in fixtures.VERSIONS}
    items = [
        DocumentListItem(
            document=document,
            latest_version=versions.get(document.latest_version_id or ""),
            latest_job_id=next(
                (job.id for job in fixtures.JOBS if job.document_id == document.id), None
            ),
        )
        for document in fixtures.DOCUMENTS
    ]
    return items[offset : offset + limit]


@router.get("/{document_id}", response_model=DocumentListItem)
def get_document(document_id: str) -> DocumentListItem:
    document = next((d for d in fixtures.DOCUMENTS if d.id == document_id), None)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    versions = {version.id: version for version in fixtures.VERSIONS}
    return DocumentListItem(
        document=document,
        latest_version=versions.get(document.latest_version_id or ""),
        latest_job_id=next(
            (job.id for job in fixtures.JOBS if job.document_id == document.id), None
        ),
    )


@router.get("/{document_id}/versions", response_model=list[DocumentVersion])
def list_versions(document_id: str) -> list[DocumentVersion]:
    return [v for v in fixtures.VERSIONS if v.document_id == document_id]


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
    return RegisterResponse(
        document=document,
        version=version,
        job_id=new_id("job"),
        upload_url=None if payload.source_uri else f"{get_settings().s3_public_endpoint_url}/{get_settings().s3_bucket}/uploads/{version_id}",
    )
