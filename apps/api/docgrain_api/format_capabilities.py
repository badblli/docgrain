"""Which Docling formats this installation can read, as the worker reported at startup.

Formats that need nothing beyond the base worker image never touch storage. For the others the
worker's probe (docgrain_worker.format_capabilities) is read from object storage; without a report
the format stays closed, so an upload is refused here instead of failing later in the worker.
"""

from __future__ import annotations

import json
import time

from docgrain_domain.docling_formats import CAPABILITIES_OBJECT
from docgrain_domain.source_format import SourceFormat, ensure_enabled, requirements

from .storage import get_text

CACHE_SECONDS = 30.0
_cache: dict[str, object] = {"at": None, "report": {}}


def worker_report() -> dict:
    now = time.monotonic()
    if _cache["at"] is not None and now - float(_cache["at"]) < CACHE_SECONDS:
        return dict(_cache["report"])  # type: ignore[arg-type]
    try:
        text = get_text(CAPABILITIES_OBJECT)
        report = json.loads(text) if text else {}
        if not isinstance(report, dict):
            report = {}
    except Exception:  # noqa: BLE001 - storage outage keeps optional formats closed, never open.
        report = {}
    _cache.update(at=now, report=report)
    return dict(report)


def available() -> dict[str, bool]:
    values = worker_report().get("available", {})
    return {str(k): v is True for k, v in values.items()} if isinstance(values, dict) else {}


def ensure_format_enabled(source_format: SourceFormat) -> None:
    """Raise FormatNotEnabled (a FormatMismatch) when a requirement is missing."""
    if requirements(source_format):
        ensure_enabled(source_format, available())
