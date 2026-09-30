"""Worker for verified source parsing and legacy PDF extraction artifacts."""

from __future__ import annotations

import json
import os
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import psycopg
import pymupdf
import redis
from docgrain_api.canonical_repository import CanonicalRepository
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import source_revision_id
from docgrain_domain.source_format import SourceFormat, declared_format, verify_format
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from minio import Minio

from .canonical_assets import store_asset
from .canonical_writer import persist_structural, processing_spec
from .quality import missing_extraction_pages, page_failures
from .structural import (
    DocumentParser,
    ParseIssue,
    StructuralParseResult,
    VerifiedSource,
)
from .vision import GeminiPageExtractor, extract_pages

QUEUE_NAME = "docgrain:pipeline"


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    path: Path
    width: int
    height: int


def document_converter() -> DocumentConverter:
    """Build the legacy PDF artifact parser; canonical parsing uses DocumentParser."""
    options = PdfPipelineOptions(do_ocr=False)
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        }
    )


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
) -> list[dict[str, object]]:
    done = {"register", "render", "extract", "quality", "publish"}
    missing_pages = missing_pages or []
    for stage in stages:
        name = str(stage["stage"])
        stage["status"] = "failed" if failed and name == failed_stage else ("done" if name in done and not failed else "skipped")
        if non_pdf and name == "render":
            stage["status"] = "skipped"
            stage["summary"] = "Not applicable to this source format."
        stage["error"] = failed if failed and name == failed_stage else None
        if name == "render" and not failed and not non_pdf:
            stage["summary"] = f"{rendered_pages} pages rendered at 200 DPI."
            stage["provider"] = "pymupdf"
            stage["attributes"] = {"pages": rendered_pages, "dpi": 200}
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
                "No page failures recorded; extraction completeness/confidence are not measured."
                if not missing_pages
                else f"{len(missing_pages)} pages failed; stage replay is not implemented."
            ))
            stage["attributes"] = {"failed_pages": missing_pages, "structural_issues": structural_issues or []}
        if name in {"normalize", "chunk", "enrich", "embed"}:
            stage["summary"] = "Not implemented."
        elif name == "vision":
            stage["summary"] = "No separate enrichment stage; configured Vision runs under extract."
        elif name == "publish" and not failed:
            stage["summary"] = ("Canonical revision persisted; no canonical artifact/manifest or index was produced."
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


def render_pages(
    source: Path, prefix: str, bucket: str, output_dir: Path
) -> list[RenderedPage]:
    """Render reviewable PDF page PNGs under the version object prefix."""
    pdf = pymupdf.open(source)
    try:
        client = storage()
        rendered: list[RenderedPage] = []
        for number, page in enumerate(pdf, start=1):
            pixmap = page.get_pixmap(dpi=200, alpha=False)
            image = pixmap.tobytes("png")
            image_path = output_dir / f"{number:04d}.png"
            image_path.write_bytes(image)
            client.put_object(
                bucket,
                f"{prefix}/pages/{number:04d}.png",
                BytesIO(image),
                len(image),
                content_type="image/png",
            )
            rendered.append(
                RenderedPage(number, image_path, pixmap.width, pixmap.height)
            )
        manifest = json.dumps(
            {
                "dpi": 200,
                "pages": [
                    {
                        "page_number": item.page_number,
                        "width": item.width,
                        "height": item.height,
                    }
                    for item in rendered
                ],
            }
        ).encode()
        client.put_object(
            bucket,
            f"{prefix}/pages.json",
            BytesIO(manifest),
            len(manifest),
            content_type="application/json",
        )
        return rendered
    finally:
        pdf.close()


def gemini_extraction(
    rendered: list[RenderedPage], prefix: str, bucket: str, api_key: str, model: str
) -> tuple[bytes, bytes, list[int], list[dict[str, object]], int, int]:
    """Run the current four-worker, three-attempt Vision extraction pass."""
    results, errors = extract_pages(
        [(page.page_number, page.path) for page in rendered],
        GeminiPageExtractor(api_key, model),
        max_workers=4,
        attempts=3,
    )
    client = storage()
    for page_number, result in results.items():
        payload = result.model_dump_json().encode()
        client.put_object(
            bucket,
            f"{prefix}/vision/{page_number:04d}.json",
            BytesIO(payload),
            len(payload),
            content_type="application/json",
        )
    ordered = [results[number] for number in sorted(results)]
    markdown = "\n\n".join(
        f"<!-- page: {page.page_number} -->\n\n{page.markdown}" for page in ordered
    ).encode()
    structured_dict = {
        "schema_name": "docgrain.multimodal-page-extraction",
        "schema_version": "1.0",
        "provider": model,
        "pages": [page.model_dump(mode="json") for page in ordered],
    }
    structured = json.dumps(structured_dict, ensure_ascii=False).encode()
    missing_pages = sorted(errors)
    failures = [
        {
            "page_number": page_number,
            "stage": "extract",
            "reason": errors[page_number],
            "resolution": "Page render was preserved; page replay is not implemented.",
        }
        for page_number in missing_pages
    ]
    return (
        markdown,
        structured,
        missing_pages,
        failures,
        sum(page.table_count for page in ordered),
        sum(page.asset_count for page in ordered),
    )


def process(job_id: str) -> None:
    with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
        cur.execute("""SELECT j.document_version_id, j.document_id, j.stages,
                             d.filename, d.mime_type, d.workspace_id, v.byte_size, v.content_sha256
                      FROM jobs j JOIN documents d ON d.id=j.document_id
                      JOIN document_versions v ON v.id=j.document_version_id
                      WHERE j.id=%s AND j.status='running'""", (job_id,))
        row = cur.fetchone()
    if row is None:
        return
    version_id, document_id, stages, filename, mime_type, workspace_id, expected_size, expected_sha = row
    bucket = os.environ["S3_BUCKET"]
    active_stage = "extract"
    try:
        with TemporaryDirectory() as temp:
            client = storage()
            object_key = f"uploads/{document_id}/{version_id}/original"
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
            try:
                structural = DocumentParser().parse(VerifiedSource(source, content_hash, len(source_bytes)), source_format)
            except Exception as exc:
                if source_format is not SourceFormat.PDF:
                    raise
                structural = StructuralParseResult(
                    source_format, "docling", "unknown", "failed", [], [], [],
                    [ParseIssue("conversion_failed", "structural_parse", source_format, None, None,
                                str(exc)[:1000], "document")],
                )
            prefix = f"artifacts/{document_id}/{version_id}"
            if structural.status == "failed" and source_format is not SourceFormat.PDF:
                raise ValueError("structural parser failed: " + "; ".join(i.reason for i in structural.issues))
            canonical_persisted = False
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
                    canonical_prefix = f"artifacts/{document_id}/{source_key[2]}"
                    for item in structural.items:
                        if item.asset_bytes:
                            digest = sha256(item.asset_bytes).hexdigest()
                            object_name = f"{canonical_prefix}/structural/assets/{digest}"
                            item.asset_path = store_asset(client, bucket, object_name, item.asset_bytes,
                                                          item.asset_mime or "application/octet-stream")
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
            if source_format is SourceFormat.PDF:
                active_stage = "render"
                rendered = render_pages(source, prefix, bucket, Path(temp))
                rendered_page_count = len(rendered)
                active_stage = "extract"
                gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
                gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
                if gemini_key:
                    markdown, structured, missing_pages, failures, table_count, asset_count = gemini_extraction(
                        rendered, prefix, bucket, gemini_key, gemini_model
                    )
                    parser = "gemini-vision"
                    vision_provider = gemini_model
                    extraction_provider = gemini_model
                else:
                    document = document_converter().convert(source).document
                    markdown = document.export_to_markdown().encode()
                    structured_dict = document.export_to_dict()
                    structured = json.dumps(structured_dict, ensure_ascii=False).encode()
                    missing_pages = missing_extraction_pages(structured_dict, rendered_page_count)
                    failures = page_failures(missing_pages)
                    table_count = len(getattr(document, "tables", []))
                    asset_count = len(getattr(document, "pictures", []))
                    parser = "docling-fallback"
                    vision_provider = None
                    extraction_provider = "docling-fallback"
                active_stage = "publish"
                client.put_object(bucket, f"{prefix}/document.md", BytesIO(markdown), len(markdown), content_type="text/markdown")
                client.put_object(bucket, f"{prefix}/document.json", BytesIO(structured), len(structured), content_type="application/json")
            else:
                rendered_page_count = 0
                missing_pages = []
                failures = []
                table_count = sum(i.kind == "table" for i in structural.items)
                asset_count = 0
                parser = structural.parser
                vision_provider = None
                extraction_provider = structural.parser
            final_status = "partial" if failures or structural_issues or not canonical_persisted else "done"
        with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE document_versions
                SET status=%s, parser=%s, vision_provider=%s, content_sha256=%s,
                    page_count=%s, table_count=%s, asset_count=%s, published_at=NOW()
                WHERE id=%s""",
                (
                    final_status,
                    parser,
                    vision_provider,
                    content_hash,
                    rendered_page_count,
                    table_count,
                    asset_count,
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
    client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True, socket_timeout=None)
    while True:
        _, job_id = client.brpop(QUEUE_NAME, timeout=0)
        with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
            cur.execute("UPDATE jobs SET status='running', started_at=COALESCE(started_at, NOW()) WHERE id=%s AND status='queued'", (job_id,))
            claimed = cur.rowcount == 1
            conn.commit()
        if claimed:
            process(job_id)


if __name__ == "__main__":
    run()
