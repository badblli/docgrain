"""Durable leases and bounded crash recovery for document jobs."""

from __future__ import annotations

import json
from uuid import uuid4

STALE_MESSAGE = "Belge okunurken ilerleme durdu. Yeniden deneme de tamamlanamadı."


def initialize(connection):
    with connection.cursor() as cur:
        cur.execute("""ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_at TIMESTAMPTZ;
            ALTER TABLE jobs ADD COLUMN IF NOT EXISTS stale_retries INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE jobs ADD COLUMN IF NOT EXISTS run_token TEXT;
            CREATE INDEX IF NOT EXISTS jobs_recovery_idx ON jobs(status, progress_at);""")


def claim(connection, job_id):
    token = str(uuid4())
    with connection.cursor() as cur:
        cur.execute("""UPDATE jobs SET status='running', started_at=NOW(), progress_at=NOW(),
            run_token=%s, finished_at=NULL, duration_ms=NULL WHERE id=%s AND status='queued'""",
                    (token, job_id))
        if cur.rowcount != 1:
            return None
        cur.execute("""UPDATE document_versions SET status='processing'
            WHERE id=(SELECT document_version_id FROM jobs WHERE id=%s)""", (job_id,))
    return token


def progress(connection, job_id, token):
    with connection.cursor() as cur:
        cur.execute("UPDATE jobs SET progress_at=NOW() WHERE id=%s AND status='running' AND run_token=%s",
                    (job_id, token))
        return cur.rowcount == 1


def promote_usable_version(connection, version_id):
    """Called in the worker's final transaction, after verified outputs and job status.

    done/partial jobs with published canonical outputs are usable. Row locking
    serializes completions; an older job finishing late cannot roll back latest.
    Failure/lease recovery never calls this function.
    """
    with connection.cursor() as cur:
        cur.execute("""SELECT d.id FROM documents d JOIN document_versions v ON v.document_id=d.id
            WHERE v.id=%s FOR UPDATE OF d""", (version_id,))
        cur.execute("""UPDATE documents d SET latest_version_id=v.id, updated_at=NOW()
            FROM document_versions v
            WHERE v.id=%s AND v.document_id=d.id AND v.workspace_id=d.workspace_id
              AND v.status IN ('done', 'partial')
              AND EXISTS (SELECT 1 FROM jobs j WHERE j.document_version_id=v.id
                          AND j.status IN ('done', 'partial'))
              AND (d.latest_version_id IS NULL OR d.latest_version_id=v.id OR
                   v.revision > (SELECT previous.revision FROM document_versions previous
                                 WHERE previous.id=d.latest_version_id))""", (version_id,))


def failure_stages(stages, code, message, failed_stage="extract"):
    for stage in stages:
        stage["status"] = "failed" if stage["stage"] == failed_stage else "skipped"
        stage["error"] = message if stage["stage"] == failed_stage else None
        if stage["stage"] == failed_stage:
            stage.setdefault("attributes", {})["structural_issues"] = [
                {"code": code, "stage": failed_stage, "reason": message, "impact": "document"}]
    return stages


def recover(connection, *, stale_seconds=900):
    """Row locks serialize sweepers; NULL progress covers jobs from older workers."""
    if stale_seconds <= 0:
        raise ValueError("stale job limit must be positive")
    with connection.cursor() as cur:
        cur.execute("""SELECT id, document_version_id, stages, stale_retries FROM jobs
            WHERE status='running' AND COALESCE(progress_at, started_at, queued_at)
                < NOW() - (%s * INTERVAL '1 second') FOR UPDATE SKIP LOCKED""", (stale_seconds,))
        for job_id, version_id, stages, retries in cur.fetchall():
            if retries == 0:
                cur.execute("""UPDATE jobs SET status='queued', stale_retries=1, run_token=NULL,
                    started_at=NULL, progress_at=NULL, finished_at=NULL, duration_ms=NULL, queued_at=NOW()
                    WHERE id=%s""", (job_id,))
                cur.execute("UPDATE document_versions SET status='processing' WHERE id=%s", (version_id,))
            else:
                stages = failure_stages(stages, "worker_stale", STALE_MESSAGE)
                cur.execute("""UPDATE jobs SET status='failed', run_token=NULL, stages=%s::jsonb,
                    finished_at=NOW() WHERE id=%s""", (json.dumps(stages), job_id))
                cur.execute("UPDATE document_versions SET status='failed' WHERE id=%s", (version_id,))
        # DB is the dispatch outbox. A failed Redis push or a crash between COMMIT/push
        # is retried on the next sweep; duplicate list entries cannot claim twice.
        # Only recovered jobs are redispatched: fresh registrations are queued before
        # upload confirmation, and must never be claimed by the sweeper.
        cur.execute("SELECT id FROM jobs WHERE status='queued' AND stale_retries > 0")
        return [row[0] for row in cur.fetchall()]
