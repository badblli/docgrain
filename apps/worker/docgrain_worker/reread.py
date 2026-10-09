"""Re-read stored hard pages: python -m docgrain_worker.reread --workspace <id>."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

import psycopg
from docgrain_api import repository
from docgrain_api.workspace_settings import ModelSettingsError, resolve_workspace_model
from docgrain_domain.source_format import declared_format, verify_format
from minio.error import S3Error

from .conversion_guard import convert
from .reading_quality import reading_report, summarize
from .selective_vision import DoclingPageReader
from .structural import VerifiedSource


def report_key(document_id: str, version_id: str) -> str:
    return f"artifacts/{document_id}/{version_id}/reading-quality.json"


def read_object(client, bucket, key, **kwargs) -> bytes:
    response = client.get_object(bucket, key, **kwargs)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def load_report(client, bucket, document_id, version_id) -> dict | None:
    try:
        return json.loads(read_object(client, bucket, report_key(document_id, version_id)))
    except S3Error as exc:
        if exc.code not in {"NoSuchKey", "NoSuchObject"}:
            raise
        return None


def save_json(client, bucket, key, payload) -> None:
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    client.put_object(bucket, key, BytesIO(data), len(data), content_type="application/json")


def model_identity(model, mode: str = "page") -> str:
    from .selective_vision import PAGE_PROMPT, PICTURE_PROMPT

    # Include endpoint, prompt and mode, but never credentials or serialized client options.
    prompt, tag = (PAGE_PROMPT, "docling-page-v2") if mode == "page" else (PICTURE_PROMPT, "docling-pictures-v1")
    return sha256(json.dumps([model.base_url.rstrip("/"), model.model, prompt, tag]).encode()).hexdigest()


def transient(exc) -> bool:
    """Only transport status codes are inspected, not raw diagnostic text."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429 or isinstance(status, int) and 500 <= status < 600:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


@contextmanager
def private_diagnostics():
    """Docling diagnostics may contain auth options or source text. Worker is serial."""
    previous = logging.root.manager.disable
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
        logging.disable(logging.CRITICAL)
        try:
            yield
        finally:
            logging.disable(previous)


def read_hard_pages(report, source, images, *, resolve=resolve_workspace_model,
                    reader_factory=DoclingPageReader, checkpoint=lambda report, proposal: None,
                    page_budget=30, timeout=120, retries=2, max_image_side=2048, sleep=time.sleep) -> dict:
    """Bounded Docling conversions. All Markdown, even hostile output, needs review.

    Hard pages (Docling low/poor grade, image files, text-less pages) go first through the VLM
    pipeline, one page per conversion; then pictures on readable PDF pages through Docling's
    picture description. Model off: no conversion and no remote call.
    """
    if (not 0 <= page_budget <= 1000 or not 0 < timeout <= 600 or not 0 <= retries <= 5
            or not 256 <= max_image_side <= 8192):
        raise ValueError("Invalid reading limits")
    report = deepcopy(report)
    data = source.path.read_bytes()
    if sha256(data).hexdigest() != report["source_sha256"] or len(data) != source.byte_size:
        raise ValueError("Source verification failed")
    image_file = report["source_format"] in {"png", "jpeg"}
    try:
        model = resolve(report["workspace_id"])
    except ModelSettingsError:
        model = None
    report["model_enabled"] = bool(model and model.enabled)
    identities = ({mode: model_identity(model, mode) for mode in ("page", "pictures")}
                  if report["model_enabled"] else {})
    tasks = [(page, "page") for page in report["pages"] if page["codes"]]
    tasks += [(page, "pictures") for page in report["pages"]
              if not page["codes"] and page.get("picture_count") and report["source_format"] == "pdf"]
    attempts = 0
    for page, mode in tasks:
        state_key, reading_key = ("state", "model_reading") if mode == "page" else ("picture_state", "picture_reading")
        number = page["page_number"]
        # Image files: Docling's budgeted page image when stored, else the verified file itself.
        image = images.get(number) or (data if image_file else None)
        if image is None:
            page[state_key] = "image_unavailable"
            continue
        digest = sha256(image).hexdigest()
        page["image_sha256"] = digest
        old = page.get(reading_key)
        if (old and old["image_sha256"] == digest
                and (not identities or old["model_identity"] == identities[mode])):
            page[state_key] = old.get("result_state", "needs_review")
            continue
        page[reading_key] = None
        page[state_key] = "waiting_model"
        if not report["model_enabled"]:
            continue
        if attempts >= page_budget:
            page[state_key] = "budget_deferred"
            continue
        try:
            # Re-resolve opt-in/key rotation just before each page, fail closed on changes.
            current = resolve(report["workspace_id"], expected_version=model.settings_version)
            if not current.enabled:
                raise ModelSettingsError("Model kapalı.")
        except ModelSettingsError:
            report["model_enabled"] = False
            continue
        attempts += 1
        identity = identities[mode]
        region = "page" if mode == "page" else "pictures"
        provenance = {"content_origin": "workspace_model", "model": current.model,
            "page_number": number, "region": region, "image_sha256": digest,
            "source_sha256": report["source_sha256"], "model_identity": identity}
        proposal = None
        for attempt in range(retries + 1):
            try:
                with private_diagnostics(), TemporaryDirectory() as directory:
                    reader = reader_factory(current, timeout=timeout, retries=retries,
                                            max_image_side=max_image_side)
                    if image_file:
                        target = Path(directory) / "page.png"
                        target.write_bytes(image)
                        markdown = reader.read(target, 1, image=True, picture=mode == "pictures")
                    else:
                        markdown = reader.read(source.path, number, image=False, picture=mode == "pictures")
                if mode == "pictures" and isinstance(markdown, str) and not markdown.strip():
                    # Every picture was below Docling's area threshold: nothing to review.
                    page[state_key] = "not_needed"
                    page[reading_key] = {**provenance, "result_state": "not_needed"}
                    break
                if (not isinstance(markdown, str) or not markdown.strip()
                        or len(markdown.encode()) > 1024 * 1024
                        or current.api_key and current.api_key in markdown):
                    page[state_key] = "model_failed"
                    break
                proposal_id = sha256(json.dumps([report["version_id"], number, region, digest, identity]).encode()).hexdigest()
                key = f"artifacts/{report['document_id']}/{report['version_id']}/reading-proposals/{proposal_id}.json"
                proposal = {"format": "docgrain.page-reading-proposal", "version": 1,
                    "document_id": report["document_id"], "version_id": report["version_id"],
                    "workspace_id": report["workspace_id"], "review_state": "needs_review",
                    "provenance": provenance, "markdown": markdown,
                    "chunks": [{"text": markdown, "review_state": "needs_review", "provenance": provenance}]}
                page[reading_key] = {**provenance, "proposal_key": key}
                page[state_key] = "needs_review"
                break
            except Exception as exc:  # noqa: BLE001 -- isolate remote failure without storing diagnostics
                page[state_key] = "model_failed"
                if attempt >= retries or not transient(exc):
                    break
                sleep(min(2 ** attempt, 4))
        checkpoint(summarize(report), proposal)
    report["attempted_pages"] = attempts
    checkpoint(summarize(report), None)
    return report


def run_reading(source, *, workspace_id, document_id, version_id, client, bucket,
                structural=None, mapping_issues=(), progress=None, tick=None, **options) -> dict:
    old = load_report(client, bucket, document_id, version_id)
    if structural is None and old is None:
        # Versions ingested before WP97: one local read in the bounded child process (WP105).
        structural = convert(source, declared_format(source.path.name, "application/octet-stream"), tick=tick)
    if structural is None:
        report = old
        images = {}
        for page in report["pages"]:
            if not (page["codes"] or page.get("picture_count")) or not page.get("image_sha256"):
                continue
            try:
                image = read_object(client, bucket, f"artifacts/{document_id}/{version_id}/reading-pages/{page['page_number']:04d}.png")
            except S3Error as exc:
                if exc.code not in {"NoSuchKey", "NoSuchObject"}:
                    raise
                continue
            if sha256(image).hexdigest() != page["image_sha256"]:
                raise ValueError("Reading image verification failed")
            images[page["page_number"]] = image
    else:
        report = reading_report(structural, document_id=document_id, version_id=version_id,
            workspace_id=workspace_id, source_sha256=source.content_sha256, mapping_issues=mapping_issues)
        images = structural.page_images
        if old and old["source_sha256"] == report["source_sha256"]:
            previous = {p["page_number"]: p for p in old["pages"]}
            for page in report["pages"]:
                for field in ("model_reading", "picture_reading"):
                    page[field] = previous.get(page["page_number"], {}).get(field)
        for page in report["pages"]:
            number = page["page_number"]
            if (page["codes"] or page.get("picture_count")) and number in images:
                data = images[number]
                client.put_object(bucket, f"artifacts/{document_id}/{version_id}/reading-pages/{number:04d}.png",
                    BytesIO(data), len(data), content_type="image/png")
    if (report["workspace_id"], report["document_id"], report["version_id"], report["source_sha256"]) != (
            workspace_id, document_id, version_id, source.content_sha256):
        raise ValueError("Reading report identity mismatch")

    def checkpoint(updated, proposal):
        if proposal:
            save_json(client, bucket, reading_proposal_key(updated, proposal), proposal)
        save_json(client, bucket, report_key(document_id, version_id), updated)
        if progress:
            progress()  # keeps the worker lease; raises when this job was taken over

    return read_hard_pages(report, source, images, checkpoint=checkpoint,
        page_budget=int(os.getenv("DOCGRAIN_READING_PAGE_BUDGET", "30")),
        timeout=float(os.getenv("DOCGRAIN_READING_PAGE_TIMEOUT", "120")),
        retries=int(os.getenv("DOCGRAIN_READING_RETRIES", "2")),
        max_image_side=int(os.getenv("DOCGRAIN_READING_MAX_IMAGE_SIDE", "2048")), **options)


def reading_proposal_key(report, proposal) -> str:
    provenance = proposal["provenance"]
    field = "model_reading" if provenance["region"] == "page" else "picture_reading"
    page = next(p for p in report["pages"] if p["page_number"] == provenance["page_number"])
    return page[field]["proposal_key"]


def reread_version(version, document, *, client, bucket, **options) -> dict:
    parsed = urlparse(version.source_uri)
    query = parse_qs(parsed.query)
    kwargs = {"version_id": query["versionId"][0]} if query.get("versionId") else {}
    with TemporaryDirectory() as directory:
        fmt = declared_format(document.filename, document.mime_type)
        path = Path(directory) / f"source.{fmt.value}"
        data = read_object(client, bucket, parsed.path.lstrip("/"), **kwargs)
        if len(data) != version.byte_size or sha256(data).hexdigest() != version.content_sha256:
            raise ValueError("Source verification failed")
        verify_format(data, fmt)
        path.write_bytes(data)
        return run_reading(VerifiedSource(path, version.content_sha256, len(data)),
            workspace_id=version.workspace_id, document_id=document.id, version_id=version.id,
            client=client, bucket=bucket, **options)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--document")
    args = parser.parse_args(argv)
    from docgrain_api.settings import get_settings
    from docgrain_api.storage import storage_client

    if get_settings().use_fixtures:
        print("Örnek görünümde yeniden okuma kapalı.")
        return 1
    documents = {d.id: d for d in repository.list_documents()
                 if d.workspace_id == args.workspace and (not args.document or d.id == args.document)}
    versions = [v for v in repository.list_versions() if v.document_id in documents
                and v.workspace_id == args.workspace and str(v.status) in {"done", "partial", "VersionStatus.DONE", "VersionStatus.PARTIAL"}]
    if not versions:
        print("Okunabilecek dosya sürümü bulunamadı.")
        return 1
    failed = False
    for version in versions:
        try:
            with closing(psycopg.connect(get_settings().database_url.replace("postgresql+psycopg://", "postgresql://"))) as conn:
                conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (f"reading:{version.id}",))
                report = reread_version(version, documents[version.document_id], client=storage_client(), bucket=get_settings().s3_bucket)
            print(f"{version.id}: {report['summary']}")
            failed |= any(p["state"] in {"model_failed", "image_unavailable"} for p in report["pages"])
        except Exception:  # noqa: BLE001 -- CLI never exposes credentials or provider diagnostics
            print(f"{version.id}: Yeniden okuma tamamlanamadı.")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
