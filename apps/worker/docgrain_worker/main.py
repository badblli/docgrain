"""Worker for verified source parsing and legacy PDF extraction artifacts."""

from __future__ import annotations

import json
import logging
import os
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import psycopg
import redis
from docgrain_api.canonical_repository import CanonicalRepository
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import source_revision_id
from docgrain_domain.source_format import SourceFormat, declared_format, verify_format
from minio import Minio

from .canonical_assets import store_asset
from .canonical_writer import persist_structural, processing_spec
from .output_writer import publish_outputs
from .quality import page_failures
from .structural import (
    DocumentParser,
    VerifiedSource,
)

QUEUE_NAME = "docgrain:pipeline"


def db_url() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def storage() -> Minio:
    parsed = urlparse(os.environ["S3_ENDPOINT_URL"])
    return Minio(parsed.netloc or parsed.path, access_key=os.environ["S3_ACCESS_KEY"], secret_key=os.environ["S3_SECRET_KEY"], secure=parsed.scheme == "https", region="us-east-1")


def stage_update(
    stages: list[dict[str, object]],
    failed: str | None = None,
    *,
    rendered_pages: int = 0,
    missing_pages: list[int] | None = None,
    extraction_provider: str = "docling",
    failed_stage: str = "extract",
    non_pdf: bool = False,
    structural_status: str | None = None,
    structural_issues: list[dict[str, object]] | None = None,
    canonical_persisted: bool = False,
    outputs_published: bool = False,
    chunk_count: int = 0,
    output_revision_id: str | None = None,
) -> list[dict[str, object]]:
    done = {"register", "render", "extract", "quality", "publish"}
    if outputs_published:
        done.update({"normalize", "chunk"})
    missing_pages = missing_pages or []
    for stage in stages:
        name = str(stage["stage"])
        stage["status"] = "failed" if failed and name == failed_stage else ("done" if name in done and not failed else "skipped")
        if non_pdf and name == "render":
            stage["status"] = "skipped"
            stage["summary"] = "Not applicable to this source format."
        stage["error"] = failed if failed and name == failed_stage else None
        if name == "render" and not failed and not non_pdf:
            stage["summary"] = f"Docling page images published for {rendered_pages} source pages."
            stage["provider"] = "docling"
            stage["attributes"] = {"pages": rendered_pages, "dpi": 144}
        elif name == "extract" and not failed:
            stage["summary"] = ("Structural extraction completed." if non_pdf else (
                f"{rendered_pages - len(missing_pages)} of {rendered_pages} pages extracted."
            ))
            stage["provider"] = extraction_provider
            stage["attributes"] = {
                "pages": rendered_pages,
                "failed_pages": missing_pages,
                "structural_status": structural_status,
                "structural_issues": structural_issues or [],
                "canonical_persisted": canonical_persisted,
            }
        elif name == "quality" and not failed:
            stage["summary"] = (f"Structural parse: {structural_status}; {len(structural_issues or [])} issues."
                                if non_pdf else (
                "Docling confidence report captured; grades do not certify source correctness."
                if not missing_pages
                else f"{len(missing_pages)} pages require source review; stage replay is not implemented."
            ))
            stage["attributes"] = {"failed_pages": missing_pages, "structural_issues": structural_issues or []}
        if name in {"normalize", "chunk"} and outputs_published and not failed:
            stage["summary"] = ("Common ai.json + canonical JSON/Markdown and verified manifest published; semantic content is not verified."
                                if name == "normalize" else f"{chunk_count} canonical chunks published; no embedding performed.")
            stage["attributes"] = {"output_revision_id":output_revision_id,"chunk_count":chunk_count}
        elif name in {"normalize", "chunk", "enrich", "embed"}:
            stage["summary"] = "Not implemented."
        elif name == "vision":
            stage["summary"] = "No separate enrichment stage; configured Vision runs under extract."
        elif name == "publish" and not failed:
            stage["summary"] = ("Verified canonical.json, ai.json, canonical.md, chunks.jsonl and manifest published; no index produced."
                                if outputs_published else
                                "Canonical revision persisted; no canonical artifact/manifest or index was produced."
                                if canonical_persisted else
                                ("Structural extraction completed; no canonical revision or PDF artifacts were published."
                                 if non_pdf else "Extraction JSON/Markdown stored; no canonical manifest or index was produced."))
    return stages


def fail(job_id: str, message: str, failed_stage: str = "extract") -> None:
    with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
        cur.execute("SELECT document_version_id, stages FROM jobs WHERE id = %s", (job_id,))
        version_id, stages = cur.fetchone()
        cur.execute("UPDATE jobs SET status='failed', stages=%s::jsonb, finished_at=NOW() WHERE id=%s", (json.dumps(stage_update(stages, message, failed_stage=failed_stage)), job_id))
        cur.execute("UPDATE document_versions SET status='failed' WHERE id=%s", (version_id,))
        conn.commit()


def publish_page_images(result, prefix: str, bucket: str) -> None:
    """Publish Docling's existing page images for the source-review API."""
    from PIL import Image
    client = storage()
    pages = []
    for number, data in sorted(result.page_images.items()):
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
        client.put_object(bucket, f"{prefix}/pages/{number:04d}.png", BytesIO(data),
                          len(data), content_type="image/png")
        pages.append({"page_number": number, "width": width, "height": height})
    manifest = json.dumps({"dpi": 144, "pages": pages}).encode()
    client.put_object(bucket, f"{prefix}/pages.json", BytesIO(manifest), len(manifest),
                      content_type="application/json")


def process(job_id: str) -> None:
    with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
        cur.execute("""SELECT j.document_version_id, j.document_id, j.stages,
                             d.filename, d.mime_type, d.workspace_id, v.byte_size, v.content_sha256, v.source_uri
                      FROM jobs j JOIN documents d ON d.id=j.document_id
                      JOIN document_versions v ON v.id=j.document_version_id
                      WHERE j.id=%s AND j.status='running'""", (job_id,))
        row = cur.fetchone()
    if row is None:
        return
    version_id, document_id, stages, filename, mime_type, workspace_id, expected_size, expected_sha, source_uri = row
    bucket = os.environ["S3_BUCKET"]
    active_stage = "extract"
    try:
        with TemporaryDirectory() as temp:
            client = storage()
            object_key = urlparse(source_uri).path.lstrip("/")
            response = client.get_object(bucket, object_key)
            source_format = declared_format(filename, mime_type)
            source = Path(temp) / f"source.{source_format.value}"
            try:
                source.write_bytes(response.read())
                storage_version = response.headers.get("x-amz-version-id")
            finally:
                response.close()
                response.release_conn()
            source_bytes = source.read_bytes()
            content_hash = sha256(source_bytes).hexdigest()
            if len(source_bytes) != expected_size:
                raise ValueError("source byte size differs from registration")
            if expected_sha != "0" * 64 and expected_sha != content_hash:
                raise ValueError("source SHA-256 differs from registration")
            verify_format(source_bytes, source_format)
            canonical_repository = CanonicalRepository(lambda: psycopg.connect(db_url()))
            expected_head = None
            if os.getenv("CANONICAL_PERSISTENCE_ENABLED", "false").lower() == "true":
                heads = canonical_repository.get_heads(document_id)
                expected_head = heads[0] if heads else None
            structural = DocumentParser().parse(
                VerifiedSource(source, content_hash, len(source_bytes)), source_format)
            prefix = f"artifacts/{document_id}/{version_id}"
            if structural.status == "failed":
                raise ValueError("structural parser failed: " + "; ".join(i.reason for i in structural.issues))
            canonical_persisted = False
            outputs_published = False
            chunk_count = 0
            output_revision_id = None
            structural_issues = [i.__dict__ for i in structural.issues]
            if os.getenv("CANONICAL_PERSISTENCE_ENABLED", "false").lower() == "true":
                if storage_version and storage_version != "null" and structural.status != "failed":
                    stat = client.stat_object(bucket, object_key, version_id=storage_version)
                    source_id = source_revision_id(workspace_id, document_id, content_hash)
                    source_version = SourceVersion(
                        id=source_id, document_id=document_id, workspace_id=workspace_id,
                        content_sha256=content_hash,
                        storage_uri=f"s3://{bucket}/{object_key}?versionId={storage_version}",
                        storage_version=storage_version, byte_size=len(source_bytes), mime_type=mime_type,
                        filename=filename, recorded_at=stat.last_modified or datetime.now(UTC),
                    )
                    stored_source = canonical_repository.get_source(source_id)
                    if stored_source:
                        source_version = stored_source
                    # The first verified receipt owns canonical asset storage on source replay.
                    source_key = urlparse(source_version.storage_uri).path.strip("/").split("/")
                    canonical_prefix = f"artifacts/{document_id}/{source_key[-2]}"
                    for item in structural.items:
                        if item.asset_bytes:
                            digest = sha256(item.asset_bytes).hexdigest()
                            object_name = f"{canonical_prefix}/structural/assets/{digest}"
                            item.asset_path = store_asset(client, bucket, object_name, item.asset_bytes,
                                                          item.asset_mime or "application/octet-stream")
                    if structural.legacy_json is not None:
                        digest = sha256(structural.legacy_json).hexdigest()
                        structural.docling_artifact_uri = store_asset(client, bucket,
                            f"{canonical_prefix}/structural/docling/{digest}.json",
                            structural.legacy_json, "application/json")
                    snapshot, _ = persist_structural(
                        canonical_repository, structural, source_version, spec=processing_spec(structural),
                        pdf_path=source if source_format is SourceFormat.PDF else None,
                        expected_latest_revision_id=expected_head,
                    )
                    canonical_persisted = True
                    structural_issues = snapshot.metadata["structural_parse"]["issues"]
                else:
                    structural_issues.append({"code": "source_not_versioned", "stage": "source_verification",
                                              "reason": "Immutable object version is unavailable; canonical persistence gated",
                                              "impact": "document"})
            rendered_page_count = len(structural.expected_areas) if source_format is SourceFormat.PDF else 0
            failures = page_failures(structural) if source_format is SourceFormat.PDF else []
            missing_pages = [failure["page_number"] for failure in failures]
            table_count = sum(i.kind == "table" for i in structural.items)
            asset_count = sum(i.kind == "picture" and bool(i.asset_bytes) for i in structural.items)
            parser = extraction_provider = structural.parser
            vision_provider = None
            if source_format is SourceFormat.PDF:
                active_stage = "render"
                publish_page_images(structural, prefix, bucket)
                active_stage = "publish"
                for name, data, mime in (("document.md", structural.legacy_markdown, "text/markdown"),
                                         ("document.json", structural.legacy_json, "application/json")):
                    if data is None:
                        raise ValueError("Docling extraction artifact unavailable")
                    client.put_object(bucket, f"{prefix}/{name}", BytesIO(data), len(data), content_type=mime)
            if canonical_persisted:
                active_stage = "publish"
                output, publication, _ = publish_outputs(canonical_repository,snapshot,client,bucket)
                outputs_published = True
                chunk_count = output.quality.measurements["chunks"]
                output_revision_id = publication.revision.id
            final_status = "partial" if failures or structural_issues or not canonical_persisted else "done"
        with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE document_versions
                SET status=%s, parser=%s, vision_provider=%s, content_sha256=%s,
                    page_count=%s, table_count=%s, asset_count=%s, chunk_count=%s, published_at=NOW()
                WHERE id=%s""",
                (
                    final_status,
                    parser,
                    vision_provider,
                    content_hash,
                    rendered_page_count,
                    table_count,
                    asset_count,
                    chunk_count,
                    version_id,
                ),
            )
            cur.execute(
                """UPDATE jobs
                SET status=%s, stages=%s::jsonb, page_failures=%s::jsonb,
                    finished_at=NOW(),
                    duration_ms=(EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)::INTEGER
                WHERE id=%s""",
                (
                    final_status,
                    json.dumps(
                        stage_update(
                            stages,
                            rendered_pages=rendered_page_count,
                            missing_pages=missing_pages,
                            extraction_provider=extraction_provider,
                            non_pdf=source_format is not SourceFormat.PDF,
                            structural_status=structural.status,
                            structural_issues=structural_issues,
                            canonical_persisted=canonical_persisted,
                            outputs_published=outputs_published,
                            chunk_count=chunk_count,
                            output_revision_id=output_revision_id,
                        )
                    ),
                    json.dumps(failures),
                    job_id,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - pipeline must persist unexpected provider failures.
        fail(job_id, str(exc)[:1000], active_stage)


def run() -> None:
    from .docling_models import startup_check

    startup_check()
    from docgrain_api.records_jobs import QUEUE_NAME as RECORDS_QUEUE

    from .records_pipeline import supervise

    client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True, socket_timeout=None)
    while True:
        queue, job_id = client.brpop([QUEUE_NAME, RECORDS_QUEUE], timeout=0)
        if queue == RECORDS_QUEUE:
            try:
                supervise(job_id)
            except Exception:  # noqa: BLE001 - GET fences stale jobs when storage is available again.
                logging.getLogger(__name__).error("record supervisor stopped (worker_stale)")
            continue
        with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
            cur.execute("UPDATE jobs SET status='running', started_at=COALESCE(started_at, NOW()) WHERE id=%s AND status='queued'", (job_id,))
            claimed = cur.rowcount == 1
            conn.commit()
        if claimed:
            process(job_id)


if __name__ == "__main__":
    run()
