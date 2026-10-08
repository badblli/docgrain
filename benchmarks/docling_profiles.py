"""Private, in-process profile measurements. Run inside the pinned worker image."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from collections import Counter
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
for package in ("apps/worker", "apps/api", "packages/domain", "packages/access"):
    sys.path.insert(0, str(ROOT / package))

from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import (
    processing_revision_id,
    source_revision_id,
)
from docgrain_domain.source_format import MIME_TYPES, SourceFormat
from docgrain_worker.canonical_mapper import CanonicalMapper, _locator
from docgrain_worker.canonical_writer import processing_spec
from docgrain_worker.docling_profiles import (
    PROFILE_IDS,
    RemoteOptions,
    hard_pages,
    validate_profile,
)
from docgrain_worker.structural import DocumentParser, VerifiedSource

FORMATS = {".pdf": SourceFormat.PDF, ".docx": SourceFormat.DOCX, ".xlsx": SourceFormat.XLSX,
           ".txt": SourceFormat.TXT, ".png": SourceFormat.PNG, ".jpg": SourceFormat.JPEG,
           ".jpeg": SourceFormat.JPEG}


def source_text(path: Path, fmt: SourceFormat) -> str | None:
    if fmt is SourceFormat.PDF:
        import pymupdf
        with pymupdf.open(path) as pdf:
            return "\n".join(page.get_text() for page in pdf)
    if fmt is SourceFormat.DOCX:
        # Join runs within paragraphs, preserve boundaries between paragraphs/cells/parts.
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with ZipFile(path) as archive:
            parts = [name for name in archive.namelist() if re.fullmatch(
                r"word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml", name)]
            return "\n".join("".join(t.text or "" for t in p.findall(".//w:t", ns))
                             for part in sorted(parts)
                             for p in ElementTree.fromstring(archive.read(part)).findall(".//w:p", ns))
    if fmt is SourceFormat.XLSX:
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            from docgrain_worker.xlsx_format import display_value
            return "\n".join(display_value(cell.value, cell.number_format) for sheet in workbook for row in sheet
                             for cell in row if cell.value is not None)
        finally:
            workbook.close()
    if fmt is SourceFormat.TXT:
        return path.read_text(encoding="utf-8-sig")
    return None


def words(text: str) -> Counter:
    return Counter(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def word_recall(reference: str | None, extracted: str) -> float | None:
    expected = words(reference or "")
    return sum((expected & words(extracted)).values()) / expected.total() if expected else None


def rss_bytes() -> int:
    if sys.platform == "win32":
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        *[(name, ctypes.c_size_t) for name in (
                            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                            "PagefileUsage", "PeakPagefileUsage")]]
        counter = Counters()
        counter.cb = ctypes.sizeof(counter)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        get_memory.restype = wintypes.BOOL
        if not get_memory(kernel.GetCurrentProcess(), ctypes.byref(counter), counter.cb):
            raise OSError("RSS measurement unavailable")
        return counter.WorkingSetSize
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")


@contextmanager
def peak_rss():
    stop = threading.Event()
    peak = [rss_bytes()]
    def sample():
        while not stop.wait(0.01):
            peak[0] = max(peak[0], rss_bytes())
    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        yield peak
    finally:
        peak[0] = max(peak[0], rss_bytes())
        stop.set()
        thread.join()


@contextmanager
def count_vlm_calls(remote: RemoteOptions | None):
    """Count logical HTTP requests to the selected endpoint (transport retries excluded)."""
    count = [0]
    if remote is None:
        yield count
        return
    import requests
    original = requests.sessions.Session.send
    lock = threading.Lock()
    def send(session, request, **kwargs):
        if request.url.rstrip("/") == remote.endpoint.rstrip("/"):
            with lock:
                count[0] += 1
        return original(session, request, **kwargs)
    requests.sessions.Session.send = send
    try:
        yield count
    finally:
        requests.sessions.Session.send = original


def measure(path: Path, profile: str, *, tolerance: float = 0,
            remote: RemoteOptions | None = None) -> dict:
    import pymupdf

    fmt = FORMATS[path.suffix.lower()]
    data = path.read_bytes()
    digest = sha256(data).hexdigest()
    verified = VerifiedSource(path, digest, len(data))
    reference = source_text(path, fmt)
    started = time.perf_counter()
    with peak_rss() as peak, count_vlm_calls(remote) as calls:
        result = DocumentParser(profile=profile,
                                remote=remote, bbox_tolerance=tolerance).parse(verified, fmt)
    elapsed = time.perf_counter() - started
    if result.status == "failed":
        raise ValueError("conversion failed")
    spec = processing_spec(result)
    source = SourceVersion(id=source_revision_id("benchmark", "document", digest),
        document_id="document", workspace_id="benchmark", content_sha256=digest,
        storage_uri="benchmark://source", storage_version="1", byte_size=len(data),
        mime_type=MIME_TYPES[fmt], filename=path.name, recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    for item in result.items:
        if item.asset_bytes:
            item.asset_path = "benchmark://image/" + sha256(item.asset_bytes).hexdigest()
    snapshot = CanonicalMapper().map(result, source, revision_id=processing_revision_id(source.id, spec),
        created_at=source.recorded_at, pdf_path=path if fmt is SourceFormat.PDF else None, processing=spec)
    extracted = "\n".join([item.text for item in result.items] +
        [str(c.get("display_text") if c.get("display_text") is not None else
             c.get("value") if c.get("value") is not None else "")
         for item in result.items for row in item.cells for c in row])
    resolved = total = 0
    pdf = pymupdf.open(path) if fmt is SourceFormat.PDF else None
    try:
        for item in result.items:
            for raw in [item.locator, *(c.get("locator") for row in item.cells for c in row)]:
                if not raw or raw.get("kind") not in {"pdf_raw", "pdf_native", "image_region"}:
                    continue
                total += 1
                mapped = _locator(raw, item.page_size, pdf, tolerance_points=tolerance)
                resolved += int(mapped is not None and mapped.bbox is not None)
    finally:
        if pdf:
            pdf.close()
    report = result.source_metadata.get("docling_confidence") or {}
    low = [int(n) for n, page in report.get("pages", {}).items() if page.get("low_grade") in {"poor", "fair"}]
    page_count = max(1, len(result.source_metadata.get("pages", {})))
    counts = Counter(item.kind for item in result.items)
    proposals = "\n".join(p["markdown"] for p in result.source_metadata.get("vlm_page_proposals", []))
    return {"profile": profile, "status": result.status, "processing_spec": spec.model_dump(mode="json"),
            "word_recall": word_recall(reference, extracted), "source_word_count": words(reference or "").total(),
            "word_recall_with_vlm_proposals": word_recall(reference, extracted + "\n" + proposals)
                if profile == "E_vlm" else None,
            "blocks": sum(counts[k] for k in ("heading", "paragraph", "list_item")),
            "tables": counts["table"], "pictures": counts["picture"], "pages": page_count,
            "bbox_resolved": resolved, "bbox_total": total,
            "resolved_bbox_ratio": resolved / total if total else None,
            "bbox_unresolved": sum(i["code"] == "bbox_unresolved" for i in snapshot.metadata["structural_parse"]["issues"]),
            "docling_confidence": snapshot.metadata.get("docling_confidence", {}),
            "docling_low_grade_pages": sorted(low),
            "hard_page_codes": hard_pages(result), "seconds": elapsed,
            "seconds_per_page": elapsed / page_count, "peak_rss_bytes": peak[0], "vlm_calls": calls[0]}


def markdown(rows: list[dict]) -> str:
    lines = ["| Dosya | Profil | Durum | Sözcük oranı | Blok/tablo/görsel | Kutu oranı | Çözülemeyen kutu | Düşük notlu sayfa | Zor sayfa kodları | sn/sayfa | RSS MiB | VLM çağrısı |",
             "|---|---|---|---:|---|---:|---:|---|---|---:|---:|---:|"]
    def value(number):
        return "—" if number is None else f"{number:.3f}"
    for row in rows:
        filename = row["file"].replace("|", "&#124;").replace("\n", " ").replace("\r", " ")
        if "error_type" in row:
            lines.append(f"| {filename} | {row['profile']} | failed ({row['error_type']}) | — | — | — | — | — | — | — | — | — |")
            continue
        codes = "; ".join(f"{n}: {', '.join(c)}" for n, c in row["hard_page_codes"].items())
        lines.append(f"| {filename} | {row['profile']} | {row['status']} | {value(row['word_recall'])} | "
            f"{row['blocks']}/{row['tables']}/{row['pictures']} | {value(row['resolved_bbox_ratio'])} | "
            f"{row['bbox_unresolved']} | {row['docling_low_grade_pages']} | {codes} | "
            f"{row['seconds_per_page']:.3f} | {row['peak_rss_bytes'] / 2**20:.1f} | {row['vlm_calls']} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", default="C_tesseract")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bbox-tolerance", type=float, default=0, help="PDF points, 0 disables clipping")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL including /v1 when required")
    parser.add_argument("--model")
    parser.add_argument("--key-env")
    args = parser.parse_args(argv)
    profiles = args.profiles.split(",")
    remote = RemoteOptions(args.base_url or "", args.model or "", args.key_env or "") if "E_vlm" in profiles else None
    try:
        if any(p not in PROFILE_IDS for p in profiles):
            raise ValueError("unknown profile")
        if not args.root.is_dir():
            raise ValueError("root must be a company-folder directory")
        if remote is None and any((args.base_url, args.model, args.key_env)):
            raise ValueError("remote arguments require E_vlm")
        for profile in profiles:
            validate_profile(profile, remote if profile == "E_vlm" else None)
            DocumentParser(profile=profile, remote=remote if profile == "E_vlm" else None,
                           bbox_tolerance=args.bbox_tolerance)
    except ValueError as exc:
        parser.error(str(exc))
    rows = []
    for company in sorted(args.root.iterdir()):
        if not company.is_dir() or company.is_symlink():
            continue
        for path in sorted(company.rglob("*")):
            if (not path.is_file() or path.is_symlink() or path.suffix.lower() not in FORMATS
                    or args.out.resolve() in path.resolve().parents):
                continue
            for profile in profiles:
                row = {"file": path.relative_to(args.root).as_posix(), "profile": profile}
                try:
                    # Docling diagnostics can contain source names/text; only private outputs expose names.
                    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
                        previous = logging.root.manager.disable
                        logging.disable(logging.CRITICAL)
                        try:
                            row.update(measure(path, profile, tolerance=args.bbox_tolerance,
                                               remote=remote if profile == "E_vlm" else None))
                        finally:
                            logging.disable(previous)
                except Exception as exc:  # noqa: BLE001 -- isolate file failures, never expose remote secrets
                    # Exception messages from remote clients may contain credentials or source text.
                    row.update(status="failed", error_type=type(exc).__name__)
                rows.append(row)
    args.out.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "created_at": datetime.now(UTC).isoformat(),
               "bbox_tolerance_points": args.bbox_tolerance, "rows": rows,
               "notes": ["No text layer: word recall is null, never inferred from OCR.",
                         "RSS is sampled absolute process resident memory; retained model caches count.",
                         "VLM calls count logical HTTP requests; transport retries are excluded.",
                         "Low grade pages are poor/fair; hard page codes are independent parser signals.",
                         "VLM proposals remain separate, unapproved page-level content."]}
    (args.out / "profiles.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    (args.out / "profiles.md").write_text(markdown(rows), encoding="utf-8")
    return int(not rows or any("error_type" in row for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
