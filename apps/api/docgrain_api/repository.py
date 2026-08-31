"""Repository boundary with fixture mode for tests and PostgreSQL for Docker."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from docgrain_domain import Document, DocumentVersion, Job
from psycopg.rows import dict_row

from . import fixtures
from .settings import get_settings


def _database_url() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


@contextmanager
def _connection() -> Iterator[psycopg.Connection[dict[str, object]]]:
    with psycopg.connect(_database_url(), row_factory=dict_row) as connection:
        yield connection


def _fixture_mode() -> bool:
    return get_settings().use_fixtures


_documents: list[Document] = [*fixtures.DOCUMENTS]
_versions: list[DocumentVersion] = [*fixtures.VERSIONS]
_jobs: list[Job] = [*fixtures.JOBS]


def initialize() -> None:
    """Create the small Milestone 0 persistence schema when fixture mode is off."""
    if _fixture_mode():
        return
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, title TEXT NOT NULL,
                filename TEXT NOT NULL, mime_type TEXT NOT NULL, latest_version_id TEXT,
                version_count INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            );
            CREATE TABLE IF NOT EXISTS document_versions (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                workspace_id TEXT NOT NULL, revision INTEGER NOT NULL, content_sha256 TEXT NOT NULL,
                source_uri TEXT NOT NULL, byte_size BIGINT NOT NULL, page_count INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL, table_count INTEGER NOT NULL, asset_count INTEGER NOT NULL,
                status TEXT NOT NULL, parser TEXT, vision_provider TEXT,
                created_at TIMESTAMPTZ NOT NULL, published_at TIMESTAMPTZ
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                document_version_id TEXT NOT NULL REFERENCES document_versions(id), workspace_id TEXT NOT NULL,
                status TEXT NOT NULL, stages JSONB NOT NULL, page_failures JSONB NOT NULL,
                queued_at TIMESTAMPTZ NOT NULL, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
                duration_ms INTEGER, correlation_id TEXT
            );
            CREATE INDEX IF NOT EXISTS documents_updated_at_idx ON documents(updated_at DESC);
            CREATE INDEX IF NOT EXISTS jobs_version_idx ON jobs(document_version_id);
            """
        )


def _document(row: dict[str, object]) -> Document:
    return Document.model_validate(row)


def _version(row: dict[str, object]) -> DocumentVersion:
    return DocumentVersion.model_validate(row)


def _job(row: dict[str, object]) -> Job:
    return Job.model_validate(row)


def add(document: Document, version: DocumentVersion, job: Job) -> None:
    if _fixture_mode():
        _documents.append(document)
        _versions.append(version)
        _jobs.append(job)
        return
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO documents VALUES (%(id)s, %(workspace_id)s, %(title)s, %(filename)s,
            %(mime_type)s, %(latest_version_id)s, %(version_count)s, %(created_at)s, %(updated_at)s)""",
            document.model_dump(),
        )
        cursor.execute(
            """INSERT INTO document_versions VALUES (%(id)s, %(document_id)s, %(workspace_id)s,
            %(revision)s, %(content_sha256)s, %(source_uri)s, %(byte_size)s, %(page_count)s,
            %(chunk_count)s, %(table_count)s, %(asset_count)s, %(status)s, %(parser)s,
            %(vision_provider)s, %(created_at)s, %(published_at)s)""",
            version.model_dump(mode="json"),
        )
        values = job.model_dump(mode="json")
        values["stages"] = json.dumps(values["stages"])
        values["page_failures"] = json.dumps(values["page_failures"])
        cursor.execute(
            """INSERT INTO jobs VALUES (%(id)s, %(document_id)s, %(document_version_id)s,
            %(workspace_id)s, %(status)s, %(stages)s::jsonb, %(page_failures)s::jsonb, %(queued_at)s,
            %(started_at)s, %(finished_at)s, %(duration_ms)s, %(correlation_id)s)""",
            values,
        )


def list_documents() -> list[Document]:
    if _fixture_mode():
        return sorted(_documents, key=lambda item: item.updated_at, reverse=True)
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM documents ORDER BY updated_at DESC")
        return [_document(row) for row in cursor.fetchall()]


def get_document(document_id: str) -> Document | None:
    if _fixture_mode():
        return next((item for item in _documents if item.id == document_id), None)
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM documents WHERE id = %s", (document_id,))
        row = cursor.fetchone()
        return _document(row) if row else None


def get_version(document_id: str, version_id: str) -> DocumentVersion | None:
    if _fixture_mode():
        return next((item for item in _versions if item.id == version_id and item.document_id == document_id), None)
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM document_versions WHERE id = %s AND document_id = %s", (version_id, document_id))
        row = cursor.fetchone()
        return _version(row) if row else None


def versions_by_id() -> dict[str, DocumentVersion]:
    return {item.id: item for item in list_versions()}


def list_versions(document_id: str | None = None) -> list[DocumentVersion]:
    if _fixture_mode():
        return [item for item in _versions if document_id is None or item.document_id == document_id]
    with _connection() as connection, connection.cursor() as cursor:
        if document_id:
            cursor.execute("SELECT * FROM document_versions WHERE document_id = %s", (document_id,))
        else:
            cursor.execute("SELECT * FROM document_versions")
        return [_version(row) for row in cursor.fetchall()]


def jobs_for_document(document_id: str) -> list[Job]:
    if _fixture_mode():
        return [item for item in _jobs if item.document_id == document_id]
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM jobs WHERE document_id = %s", (document_id,))
        return [_job(row) for row in cursor.fetchall()]


def job_for_version(version_id: str) -> Job | None:
    if _fixture_mode():
        return next((item for item in _jobs if item.document_version_id == version_id), None)
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM jobs WHERE document_version_id = %s", (version_id,))
        row = cursor.fetchone()
        return _job(row) if row else None


def list_jobs() -> list[Job]:
    if _fixture_mode():
        return [*_jobs]
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM jobs ORDER BY queued_at DESC")
        return [_job(row) for row in cursor.fetchall()]


def get_job(job_id: str) -> Job | None:
    if _fixture_mode():
        return next((item for item in _jobs if item.id == job_id), None)
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        row = cursor.fetchone()
        return _job(row) if row else None
