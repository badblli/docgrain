"""Explicit demo/live unit-test setup; no external services are contacted."""

from contextlib import nullcontext

import pytest
from docgrain_api import repository
from docgrain_api.settings import get_settings


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "use_fixtures", True)
    monkeypatch.setattr(settings, "gemini_api_key", "")


@pytest.fixture
def live_repository(monkeypatch):
    """Exercise live routes against isolated metadata, without PostgreSQL."""
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    records = {"documents": {}, "versions": {}, "jobs": {}}
    monkeypatch.setattr(repository, "registration_lock", lambda *args: nullcontext())

    def add(document, version, job):
        records["documents"][document.id] = document
        records["versions"][version.id] = version
        records["jobs"][job.id] = job

    def get_version(document_id, version_id):
        version = records["versions"].get(version_id)
        return version if version and version.document_id == document_id else None

    monkeypatch.setattr(repository, "add", add)
    monkeypatch.setattr(repository, "get_document", records["documents"].get)
    monkeypatch.setattr(repository, "get_version", get_version)
    monkeypatch.setattr(repository, "get_job", records["jobs"].get)
    monkeypatch.setattr(repository, "list_documents", lambda: list(records["documents"].values()))
    monkeypatch.setattr(repository, "list_versions", lambda document_id=None: [
        version for version in records["versions"].values()
        if document_id is None or version.document_id == document_id
    ])
    def list_workspaces():
        counts: dict[str, dict[str, object]] = {}
        for doc in sorted(records["documents"].values(), key=lambda d: d.updated_at, reverse=True):
            if doc.workspace_id not in counts:
                counts[doc.workspace_id] = {"id": doc.workspace_id, "documents": 1}
            else:
                counts[doc.workspace_id]["documents"] = int(counts[doc.workspace_id]["documents"]) + 1
        return list(counts.values())

    monkeypatch.setattr(repository, "list_workspaces", list_workspaces)
    monkeypatch.setattr(repository, "list_jobs", lambda: list(records["jobs"].values()))
    monkeypatch.setattr(repository, "jobs_for_document", lambda document_id: [
        job for job in records["jobs"].values() if job.document_id == document_id
    ])
    monkeypatch.setattr(repository, "job_for_version", lambda version_id: next((
        job for job in records["jobs"].values() if job.document_version_id == version_id
    ), None))
    return records
