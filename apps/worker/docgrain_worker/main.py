"""Durable Docling worker: source object to canonical artifacts."""

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
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from minio import Minio

from .quality import missing_extraction_pages, page_failures
from .vision import GeminiPageExtractor, extract_pages

QUEUE_NAME = "docgrain:pipeline"


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    path: Path
    width: int
    height: int


def document_converter() -> DocumentConverter:
    """Build the deterministic secondary parser used after page rendering.

    OCR is deliberately disabled here. Gemini Vision owns page reading in the
    target architecture; until it is configured, pages without a reliable text
    layer must become partial instead of being silently rewritten by local OCR.
    """
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
) -> list[dict[str, object]]:
    now = datetime.now(UTC).isoformat()
    done = {"register", "render", "extract", "quality", "normalize", "publish"}
    missing_pages = missing_pages or []
    for stage in stages:
        name = str(stage["stage"])
        stage["status"] = "failed" if failed and name == "extract" else ("done" if name in done and not failed else "skipped")
        stage["error"] = failed if failed and name == "extract" else None
        if name in done and not failed:
            stage.update(started_at=now, finished_at=now, attempt=1)
        if name == "render" and not failed:
            stage["summary"] = f"{rendered_pages} pages rendered at 200 DPI."
            stage["provider"] = "pymupdf"
            stage["attributes"] = {"pages": rendered_pages, "dpi": 200}
        elif name == "extract" and not failed:
            stage["summary"] = (
                f"{rendered_pages - len(missing_pages)} of {rendered_pages} pages extracted."
            )
            stage["provider"] = extraction_provider
            stage["attributes"] = {
                "pages": rendered_pages,
                "failed_pages": missing_pages,
            }
        elif name == "quality" and not failed:
            stage["summary"] = (
                "All rendered pages have valid parser output."
                if not missing_pages
                else f"{len(missing_pages)} pages require multimodal retry."
            )
            stage["attributes"] = {"failed_pages": missing_pages}
    return stages


def fail(job_id: str, message: str) -> None:
    with closing(psycopg.connect(db_url())) as conn, conn.cursor() as cur:
        cur.execute("SELECT document_version_id, stages FROM jobs WHERE id = %s", (job_id,))
        version_id, stages = cur.fetchone()
        cur.execute("UPDATE jobs SET status='failed', stages=%s::jsonb, finished_at=NOW() WHERE id=%s", (json.dumps(stage_update(stages, message)), job_id))
        cur.execute("UPDATE document_versions SET status='failed' WHERE id=%s", (version_id,))
        conn.commit()


def render_pages(
    source: Path, prefix: str, bucket: str, output_dir: Path
) -> list[RenderedPage]:
    """Render reviewable page PNGs; each is an immutable version artifact."""
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
    """Run the artifact-approved four-page parallel, three-attempt vision pass."""
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
            "resolution": "Page render was preserved; retry this page.",
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
                response.close()
                response.release_conn()
            prefix = f"artifacts/{document_id}/{version_id}"
            rendered = render_pages(source, prefix, bucket, Path(temp))
            rendered_page_count = len(rendered)
            gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
            gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
            if gemini_key:
                (
                    markdown,
                    structured,
                    missing_pages,
                    failures,
                    table_count,
                    asset_count,
                ) = gemini_extraction(
                    rendered, prefix, bucket, gemini_key, gemini_model
                )
                parser = "gemini-vision"
                vision_provider = gemini_model
                extraction_provider = gemini_model
            else:
                document = document_converter().convert(source).document
                markdown = document.export_to_markdown().encode()
                structured_dict = document.export_to_dict()
                structured = json.dumps(
                    structured_dict, ensure_ascii=False
                ).encode()
                missing_pages = missing_extraction_pages(
                    structured_dict, rendered_page_count
                )
                failures = page_failures(missing_pages)
                table_count = len(getattr(document, "tables", []))
                asset_count = len(getattr(document, "pictures", []))
                parser = "docling-fallback"
                vision_provider = None
                extraction_provider = "docling-fallback"
            final_status = "partial" if failures else "done"
            content_hash = sha256(source.read_bytes()).hexdigest()
            client = storage()
            client.put_object(bucket, f"{prefix}/document.md", BytesIO(markdown), len(markdown), content_type="text/markdown")
            client.put_object(bucket, f"{prefix}/document.json", BytesIO(structured), len(structured), content_type="application/json")
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
                        )
                    ),
                    json.dumps(failures),
                    job_id,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - pipeline must persist unexpected provider failures.
        fail(job_id, str(exc)[:1000])


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
