"""Register, upload, confirm and observe a folder without model calls."""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import httpx
from docgrain_domain.docling_formats import NOT_ENABLED_MESSAGE
from docgrain_domain.source_format import (
    FormatMismatch,
    format_for_filename,
    mime_for_filename,
)

TERMINAL = {"done", "partial", "failed"}


def _json(client: httpx.Client, method: str, url: str, **kwargs):
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()


def _issues(job: dict) -> list[dict]:
    issues = list(job.get("page_failures", []))
    for stage in job.get("stages", []):
        if stage.get("error"):
            issues.append({"stage": stage["stage"], "reason": stage["error"]})
        for issue in stage.get("attributes", {}).get("structural_issues", []):
            if issue not in issues:
                issues.append(issue)
    return issues


def _not_enabled(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code != 415:
        return False
    try:
        return exc.response.json().get("detail") == NOT_ENABLED_MESSAGE
    except ValueError:
        return False


def ingest_folder(folder: Path, workspace_id: str, client: httpx.Client, *,
                  report_path: Path, timeout: float = 600, poll_interval: float = 1) -> dict:
    """A new invocation always asks the API to reuse persisted content hashes.

    Timeout is per file. Partial/failed jobs and transport errors are reported;
    one bad file does not prevent the rest of the folder being attempted.
    """
    folder = folder.resolve()
    report_path = report_path.resolve()
    if not folder.is_dir():
        raise ValueError("Klasör bulunamadı.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", workspace_id):
        raise ValueError("Çalışma alanı: harf, rakam, alt çizgi veya tire kullanın.")
    if timeout <= 0 or poll_interval < 0:
        raise ValueError("Bekleme süresi pozitif, kontrol aralığı sıfır veya pozitif olmalı.")
    report = {"workspace_id": workspace_id, "files": []}
    # Snapshot before writing the report; generated reports must not become sources.
    paths = sorted(folder.rglob("*"))
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")

    save()
    for path in paths:
        if path.resolve() == report_path or (path.is_dir() and not path.is_symlink()):
            continue
        row = {"file": path.relative_to(folder).as_posix(), "document_id": None,
               "version_id": None, "job_id": None, "sha256": None,
               "reused": False, "status": "skipped", "pages": None, "issues": []}
        report["files"].append(row)
        if path.is_symlink():
            row["issues"].append({"reason": "Sembolik bağlantı atlandı."})
            save()
            continue
        # KULLANILMIYOR (karar 18): WP106 öncesi altı uzantılık kontrol.
        # suffix = path.suffix.lower().lstrip(".")
        # source_format = SourceFormat("jpeg" if suffix == "jpg" else suffix)
        try:
            # WP106: every extension Docling reads (docling_formats); closed ones are refused by the API.
            format_for_filename(path.name)
        except FormatMismatch:
            row["issues"].append({"reason": "Desteklenmeyen dosya türü."})
            save()
            continue
        try:
            data = path.read_bytes()
            if not data:
                raise ValueError("Dosya boş.")
            row["sha256"] = hashlib.sha256(data).hexdigest()
            # KULLANILMIYOR (karar 18): mime = MIME_TYPES[source_format]
            mime = mime_for_filename(path.name)
            registration = _json(client, "POST", "/v1/documents", json={
                "workspace_id": workspace_id, "filename": path.name, "mime_type": mime,
                "byte_size": len(data), "content_sha256": row["sha256"],
            })
            document, version = registration["document"], registration["version"]
            if document["workspace_id"] != workspace_id or version["workspace_id"] != workspace_id:
                raise ValueError("Yanıtın çalışma alanı eşleşmiyor.")
            row.update(document_id=document["id"], version_id=version["id"],
                       job_id=registration["job_id"], reused=registration["deduplicated"])
            if registration.get("upload_url"):
                # Proxy endpoint is relative to --api, even if the server advertises localhost.
                _json(client, "PUT", f"/v1/documents/{document['id']}/versions/{version['id']}/content",
                      files={"file": (document["filename"], data, document["mime_type"])})
            job = _json(client, "GET", f"/v1/jobs/{row['job_id']}")
            if job["status"] == "queued":
                # Also repairs an interruption between storing bytes and confirmation.
                _json(client, "POST", f"/v1/documents/{document['id']}/versions/{version['id']}/uploaded")
            deadline = time.monotonic() + timeout
            while job["status"] not in TERMINAL:
                if time.monotonic() >= deadline:
                    row["issues"].append({"reason": "İşlem bekleme süresi doldu."})
                    break
                time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
                job = _json(client, "GET", f"/v1/jobs/{row['job_id']}")
            row["status"] = job["status"] if job["status"] in TERMINAL else "timeout"
            row["issues"].extend(_issues(job))
            version = _json(client, "GET", f"/v1/versions/{version['id']}")
            row["pages"] = version["page_count"]
        except (OSError, ValueError, httpx.HTTPError) as exc:
            row["status"] = "error"
            # Never copy server response bodies or source content into the report.
            reason = (f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError)
                      else type(exc).__name__ if isinstance(exc, (OSError, httpx.HTTPError)) else str(exc))
            if _not_enabled(exc):
                # A known product sentence, compared exactly; other response bodies are never copied.
                row["status"] = "skipped"
                reason = NOT_ENABLED_MESSAGE
            row["issues"].append({"reason": reason})
        save()
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="docgrain")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest-folder", help="Şirket klasörünü yükle")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--workspace", required=True)
    ingest.add_argument("--api", default="http://localhost:8000")
    ingest.add_argument("--report", type=Path)
    ingest.add_argument("--timeout", type=float, default=600)
    ingest.add_argument("--poll-interval", type=float, default=1)
    args = parser.parse_args(argv)
    report_path = args.report or Path(f"bundle-{args.workspace}.json")
    try:
        with httpx.Client(base_url=args.api.rstrip("/"), timeout=60) as client:
            report = ingest_folder(args.path, args.workspace, client, report_path=report_path,
                                   timeout=args.timeout, poll_interval=args.poll_interval)
    except (ValueError, OSError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1
    print(f"Yükleme raporu: {report_path}")
    return int(any(row["status"] not in {"done", "skipped"} for row in report["files"]))
