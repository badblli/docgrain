"""Durable Docling worker: source object to canonical artifacts."""

from __future__ import annotations

import json
import os
from contextlib import closing
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import fitz
import psycopg
import redis
from docling.document_converter import DocumentConverter
from minio import Minio

QUEUE_NAME = "docgrain:pipeline"


def db_url() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def storage() -> Minio:
    parsed = urlparse(os.environ["S3_ENDPOINT_URL"])
    return Minio(parsed.netloc or parsed.path, access_key=os.environ["S3_ACCESS_KEY"], secret_key=os.environ["S3_SECRET_KEY"], secure=parsed.scheme == "https", region="us-east-1")


def stage_update(stages: list[dict[str, object]], failed: str | None = None) -> list[dict[str, object]]:
    now = datetime.now(UTC).isoformat()
    done = {"register", "render", "extract", "normalize", "publish"}
    for stage in stages:
        name = str(stage["stage"])
        stage["status"] = "failed" if failed and name == "extract" else ("done" if name in done and not failed else "skipped")
        stage["error"] = failed if failed and name == "extract" else None
        if name in done and not failed:
            stage.update(started_at=now, finished_at=now, attempt=1)
    return stages


def fail(job_id: str, message: str) -> None:
    with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
        cur.execute("SELECT document_version_id, stages FROM jobs WHERE id = %s", (job_id,))
        version_id, stages = cur.fetchone()
        cur.execute("UPDATE jobs SET status='failed', stages=%s::jsonb, finished_at=NOW() WHERE id=%s", (json.dumps(stage_update(stages, message)), job_id))
        cur.execute("UPDATE document_versions SET status='failed' WHERE id=%s", (version_id,))
        conn.commit()


def render_pages(source: Path, prefix: str, bucket: str) -> int:
    """Render reviewable page PNGs; each is an immutable version artifact."""
    pdf = fitz.open(source)
    try:
        client = storage()
        for number, page in enumerate(pdf, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = pixmap.tobytes("png")
            client.put_object(
                bucket,
                f"{prefix}/pages/{number:04d}.png",
                BytesIO(image),
                len(image),
                content_type="image/png",
            )
        return len(pdf)
    finally:
        pdf.close()


def process(job_id: str) -> None:
    with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
        cur.execute("SELECT document_version_id, document_id, stages FROM jobs WHERE id=%s AND status='running'", (job_id,))
        row = cur.fetchone()
    if row is None:
        return
    version_id, document_id, stages = row
    bucket = os.environ["S3_BUCKET"]
    try:
        with TemporaryDirectory() as temp:
            response = storage().get_object(bucket, f"uploads/{document_id}/{version_id}/original")
            source = Path(temp) / "source.pdf"
            try:
                source.write_bytes(response.read())
            finally:
                response.close(); response.release_conn()
            prefix = f"artifacts/{document_id}/{version_id}"
            rendered_page_count = render_pages(source, prefix, bucket)
            document = DocumentConverter().convert(source).document
            markdown = document.export_to_markdown().encode()
            structured = json.dumps(document.export_to_dict(), ensure_ascii=False).encode()
            client = storage()
            client.put_object(bucket, f"{prefix}/document.md", BytesIO(markdown), len(markdown), content_type="text/markdown")
            client.put_object(bucket, f"{prefix}/document.json", BytesIO(structured), len(structured), content_type="application/json")
            page_count = len(getattr(document, "pages", {})) or rendered_page_count
        with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
            cur.execute("UPDATE document_versions SET status='done', parser='docling', page_count=%s, published_at=NOW() WHERE id=%s", (page_count, version_id))
            cur.execute("UPDATE jobs SET status='done', stages=%s::jsonb, finished_at=NOW() WHERE id=%s", (json.dumps(stage_update(stages)), job_id))
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - pipeline must persist unexpected provider failures.
        fail(job_id, str(exc)[:1000])


def run() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True, socket_timeout=None)
    while True:
        _, job_id = client.brpop(QUEUE_NAME, timeout=0)
        with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
            cur.execute("UPDATE jobs SET status='running', started_at=COALESCE(started_at, NOW()) WHERE id=%s AND status='queued'", (job_id,))
            claimed = cur.rowcount == 1; conn.commit()
        if claimed:
            process(job_id)


if __name__ == "__main__":
    run()
