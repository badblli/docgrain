"""Temporary in-memory repository.

The API boundary already uses repository functions so PostgreSQL can replace
this module without changing route behavior.
"""

from __future__ import annotations

from docgrain_domain import Document, DocumentVersion, Job

from . import fixtures

documents: list[Document] = [*fixtures.DOCUMENTS]
versions: list[DocumentVersion] = [*fixtures.VERSIONS]
jobs: list[Job] = [*fixtures.JOBS]


def add(document: Document, version: DocumentVersion, job: Job) -> None:
    documents.append(document)
    versions.append(version)
    jobs.append(job)


def list_documents() -> list[Document]:
    return sorted(documents, key=lambda item: item.updated_at, reverse=True)


def versions_by_id() -> dict[str, DocumentVersion]:
    return {item.id: item for item in versions}


def jobs_for_document(document_id: str) -> list[Job]:
    return [item for item in jobs if item.document_id == document_id]
