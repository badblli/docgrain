"""Stored version reports and explicit worker dispatch; no extraction in the API."""

from __future__ import annotations

import json

from docgrain_domain import new_id
from fastapi import APIRouter, HTTPException

from .. import repository
from ..queue import enqueue
from ..settings import get_settings
from ..storage import get_text

router = APIRouter(prefix="/v1/documents", tags=["documents"])


def require_version(document_id, version_id, workspace_id=None):
    document = repository.get_document(document_id)
    version = repository.get_version(document_id, version_id)
    if (document is None or version is None or document.workspace_id != version.workspace_id
            or workspace_id is not None and version.workspace_id != workspace_id):
        raise HTTPException(404, "Dosya sürümü bulunamadı.")
    return version


@router.get("/{document_id}/versions/{version_id}/reading-quality")
def get_report(document_id: str, version_id: str, workspace_id: str | None = None):
    version = require_version(document_id, version_id, workspace_id)
    if get_settings().use_fixtures:
        raise HTTPException(404, "Bu dosya sürümünün okuma raporu henüz yok.")
    try:
        raw = get_text(f"artifacts/{document_id}/{version_id}/reading-quality.json")
        if raw is None:
            raise HTTPException(404, "Bu dosya sürümünün okuma raporu henüz yok.")
        report = json.loads(raw)
        if (report["document_id"], report["version_id"], report["workspace_id"], report["source_sha256"]) != (
                document_id, version_id, version.workspace_id, version.content_sha256):
            raise ValueError
        return report
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 -- storage failures never expose raw diagnostics
        raise HTTPException(503, "Okuma raporu şu anda alınamadı.") from None


@router.get("/{document_id}/versions/{version_id}/reading-quality/pages/{page_number}/proposal")
def get_proposal(document_id: str, version_id: str, page_number: int, workspace_id: str | None = None):
    report = get_report(document_id, version_id, workspace_id)
    page = next((p for p in report["pages"] if p["page_number"] == page_number), None)
    reading = page.get("model_reading") if page else None
    if not reading:
        raise HTTPException(404, "Bu sayfanın okuma önerisi henüz yok.")
    try:
        key = reading["proposal_key"]
        prefix = f"artifacts/{document_id}/{version_id}/reading-proposals/"
        if not key.startswith(prefix) or "/" in key[len(prefix):] or ".." in key:
            raise ValueError
        proposal = json.loads(get_text(key) or "null")
        if (proposal["document_id"], proposal["version_id"], proposal["workspace_id"], proposal["review_state"]) != (
                document_id, version_id, report["workspace_id"], "needs_review"):
            raise ValueError
        if any(proposal["provenance"][name] != reading[name] for name in (
                "page_number", "image_sha256", "source_sha256", "model_identity")):
            raise ValueError
        return proposal
    except Exception:  # noqa: BLE001 -- fixed public message, never leak storage diagnostics
        raise HTTPException(503, "Okuma önerisi şu anda alınamadı.") from None


def dispatch_reread(version) -> str:
    job_id = new_id("job")
    # The worker's claim marks the version processing; the reread job restores this status when it ends.
    previous = getattr(version.status, "value", version.status)
    stages = json.dumps([{"stage": "quality", "status": "pending", "attributes": {
        "reading_reread": True, "previous_version_status": previous}}])
    # Same version serializes CLI, ingestion and reread checkpoints. No queue-loop changes.
    with repository._connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (f"reading:{version.id}",))
        if not cur.fetchone()[0]:
            raise HTTPException(409, "Bu dosya sürümü zaten işleniyor.")
        cur.execute("SELECT id FROM jobs WHERE document_version_id=%s AND status IN ('queued', 'running')", (version.id,))
        if cur.fetchone():
            raise HTTPException(409, "Bu dosya sürümü zaten işleniyor.")
        cur.execute("""INSERT INTO jobs
            (id, document_id, document_version_id, workspace_id, status, stages, page_failures, queued_at)
            VALUES (%s, %s, %s, %s, 'queued', %s::jsonb, '[]'::jsonb, NOW())""",
            (job_id, version.document_id, version.id, version.workspace_id, stages))
    try:
        enqueue(job_id)
    except Exception:  # noqa: BLE001 -- explicit dispatch failure, no provider diagnostics
        with repository._connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE jobs SET status='failed', finished_at=NOW() WHERE id=%s AND status='queued'", (job_id,))
        raise HTTPException(503, "Yeniden okuma sıraya alınamadı; tekrar deneyin.") from None
    return job_id


@router.post("/{document_id}/versions/{version_id}/reread", status_code=202)
def reread(document_id: str, version_id: str, workspace_id: str | None = None):
    version = require_version(document_id, version_id, workspace_id)
    if get_settings().use_fixtures:
        raise HTTPException(409, "Örnek görünümde yeniden okuma kapalı.")
    if getattr(version.status, "value", version.status) not in {"done", "partial"}:
        raise HTTPException(409, "Önce dosyanın okunmasının tamamlanmasını bekleyin.")
    try:
        job_id = dispatch_reread(version)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 -- fixed public message
        raise HTTPException(503, "Yeniden okuma şu anda başlatılamadı.") from None
    return {"job_id": job_id, "status": "queued"}
