"""Format dispatch around DocumentParser for the formats added in WP106.

The six original formats keep their exact paths in structural.py. Everything else Docling reads
goes through the same ``_docling`` call with Docling's default backend for its InputFormat
(``build_converter`` passes ``InputFormat(fmt.value)``, which is why SourceFormat values equal
Docling's InputFormat values). A format whose reader needs something this image lacks is
returned as a failed parse with the Turkish reason instead of failing inside Docling.
"""

from __future__ import annotations

import importlib.metadata

from docgrain_domain.docling_formats import NOT_ENABLED_MESSAGE, ORIGINAL_FORMATS
from docgrain_domain.source_format import (
    SourceFormat,
    missing_requirements,
    requirements,
    resolve_format,
)

from .structural import ParseIssue, StructuralParseResult


def resolve_source_format(data: bytes, source_format: SourceFormat) -> SourceFormat:
    return resolve_format(data, source_format)


def closed_format_result(source_format: SourceFormat) -> StructuralParseResult | None:
    if not requirements(source_format):
        return None
    from .format_capabilities import cached_probe

    missing = missing_requirements(source_format, cached_probe())
    if not missing:
        return None
    try:
        version = importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        version = "unavailable"
    issue = ParseIssue("format_not_enabled", "structural_parse", source_format, None, None,
                       f"{NOT_ENABLED_MESSAGE} Eksik: {', '.join(missing)}", "document")
    return StructuralParseResult(source_format, "docling", version, "failed", [], [], [], [issue])


def mark_document_area(result: StructuralParseResult) -> None:
    """Non-paged Docling formats are read as one document area, like DOCX.

    Docling 2.130 returns ConversionStatus.FAILURE with an empty document when a backend rejects
    its input (seen with an XBRL instance without taxonomy); that must not look like a complete read.
    """
    if result.source_format.value in ORIGINAL_FORMATS or result.status == "failed":
        return
    status = str(result.source_metadata.get("docling_status", "")).lower()
    if status.endswith(("failure", "skipped")):
        result.status = "failed"
        result.items = []
        result.issues.append(ParseIssue("conversion_failed", "structural_parse", result.source_format, None, None,
                                        "Docling bu dosyayı okuyamadı.", "document"))
        return
    if not result.expected_areas:
        result.expected_areas = ["document"]
        result.processed_areas = ["document"]
    if not any(item.text or item.cells or item.asset_bytes for item in result.items):
        result.issues.append(ParseIssue("empty_document", "structural_parse", result.source_format, "document", None,
                                        "Belgede okunabilir içerik bulunamadı.", "document"))
        result.status = "partial"
