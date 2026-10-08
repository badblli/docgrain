"""Durable U1 jobs. Redis carries IDs only; PostgreSQL owns state, never credentials."""

import json
from datetime import UTC, datetime

from . import repository

ACTIVE = {"queued", "running"}


def initialize():
    with repository._connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS record_jobs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, request_id TEXT NOT NULL,
                status TEXT NOT NULL, queued_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL,
                UNIQUE(workspace_id, request_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS record_jobs_one_active
                ON record_jobs(workspace_id) WHERE status IN ('queued', 'running');
            CREATE INDEX IF NOT EXISTS record_jobs_latest ON record_jobs(workspace_id, queued_at DESC);
            CREATE TABLE IF NOT EXISTS record_job_requests (
                workspace_id TEXT NOT NULL, request_id TEXT NOT NULL,
                job_id TEXT NOT NULL REFERENCES record_jobs(id),
                PRIMARY KEY(workspace_id, request_id)
            );
        """)


def _read(where, parameters, order=""):
    with repository._connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT payload FROM record_jobs WHERE {where} {order} LIMIT 1", parameters)
        row = cur.fetchone()
        return row["payload"] if row else None


def get(workspace, job_id):
    return _read("workspace_id=%s AND id=%s", (workspace, job_id))


def latest(workspace):
    return _read("workspace_id=%s", (workspace,), "ORDER BY queued_at DESC, id DESC")


def active(workspace):
    return _read("workspace_id=%s AND status IN ('queued','running')", (workspace,))


def requested(workspace, request_id):
    return _read("workspace_id=%s AND id=(SELECT job_id FROM record_job_requests "
                 "WHERE workspace_id=%s AND request_id=%s)", (workspace, workspace, request_id))


def remember_request(workspace, request_id, job_id):
    with repository._connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO record_job_requests VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (workspace, request_id, job_id))


def create(job):
    """Caller holds the shared workspace lock; constraints also defend DB writers."""
    with repository._connection() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO record_jobs VALUES (%s,%s,%s,%s,%s,%s::jsonb)""",
                    (job["job_id"], job["workspace_id"], job["request_id"], job["status"],
                     job["queued_at"], json.dumps(job)))
        cur.execute("INSERT INTO record_job_requests VALUES (%s,%s,%s)",
                    (job["workspace_id"], job["request_id"], job["job_id"]))


def change(workspace, job_id, mutate, statuses=ACTIVE):
    """Row-locked read/modify/write prevents heartbeat and stage lost updates."""
    with repository._connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload FROM record_jobs WHERE workspace_id=%s AND id=%s FOR UPDATE",
                    (workspace, job_id))
        row = cur.fetchone()
        if not row or row["payload"]["status"] not in statuses:
            return None
        job = row["payload"]
        mutate(job)
        job["updated_at"] = datetime.now(UTC).isoformat()
        cur.execute("UPDATE record_jobs SET status=%s,payload=%s::jsonb WHERE id=%s",
                    (job["status"], json.dumps(job), job_id))
        return job


def locate(job_id):
    return _read("id=%s", (job_id,))
