"""Probe what each Docling format needs in this image and publish it for the API (WP106).

Every probe reads the installed Docling 2.130 code paths named in docling_formats.REQUIREMENTS:
LibreOffice via docling.backend.docx.drawingml.utils.get_libreoffice_cmd (legacy DOC/RTF/PPT/XLS),
the optional modules the OpenDocument/XBRL/ASR backends import, and the ffmpeg binary the ASR and
video pipelines call. Profiles Docgrain has not wired yet stay False here on purpose.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import sys
from datetime import UTC, datetime
from functools import lru_cache
from io import BytesIO

from docgrain_domain.docling_formats import (
    CAPABILITIES_OBJECT,
    DOCLING_INPUT_FORMATS,
    DOCLING_VERSION,
)

# Reading profiles that are not wired into docling_profiles.build_converter yet.
ASR_PROFILE_READY = False  # needs AsrPipelineOptions with the baked Whisper directory as artifacts_path
METS_PROFILE_READY = False  # needs StandardPdfPipeline options with the pinned layout models


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _libreoffice() -> bool:
    try:
        from docling.backend.docx.drawingml.utils import get_libreoffice_cmd
    except ImportError:
        return False
    return get_libreoffice_cmd() is not None


def probe() -> dict[str, bool]:
    return {
        "libreoffice": _libreoffice(),
        "odfdo": _module("odfdo"),
        "arelle": _module("arelle"),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "openai-whisper": _module("whisper"),
        "asr-profile": ASR_PROFILE_READY,
        "mets-profile": METS_PROFILE_READY,
        "ebcdic-layout": False,
    }


@lru_cache(maxsize=1)
def cached_probe() -> dict[str, bool]:
    return probe()


def live_snapshot() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    from docling.datamodel.base_models import (
        FormatToExtensions,
        FormatToMimeType,
        InputFormat,
    )

    return {fmt.value: (tuple(FormatToExtensions.get(fmt, [])), tuple(FormatToMimeType.get(fmt) or []))
            for fmt in InputFormat}


def snapshot_matches() -> bool:
    import importlib.metadata

    return (importlib.metadata.version("docling") == DOCLING_VERSION
            and live_snapshot() == DOCLING_INPUT_FORMATS)


def report() -> dict:
    return {"docling_version": DOCLING_VERSION, "snapshot_matches": snapshot_matches(),
            "available": cached_probe(), "checked_at": datetime.now(UTC).isoformat()}


def publish(client, bucket: str) -> dict:
    value = report()
    if not value["snapshot_matches"]:
        logging.getLogger(__name__).error(
            "installed Docling formats differ from docgrain_domain.docling_formats; regenerate the snapshot")
    body = json.dumps(value, sort_keys=True).encode()
    client.put_object(bucket, CAPABILITIES_OBJECT, BytesIO(body), length=len(body),
                      content_type="application/json")
    return value


if __name__ == "__main__":  # pragma: no cover - maintenance entry point inside the worker image
    if sys.argv[1:] == ["--snapshot"]:
        for name, (extensions, mimes) in live_snapshot().items():
            print(f"    {json.dumps(name)}: ({extensions!r}, {mimes!r}),".replace("'", '"'))
    else:
        print(json.dumps(report(), indent=2))
