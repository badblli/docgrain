"""Pure quality checks for parser output."""

from __future__ import annotations

from typing import Any


def missing_extraction_pages(
    structured: dict[str, Any], rendered_page_count: int
) -> list[int]:
    """Return pages Docling did not represent with valid page dimensions.

    Empty pages are legitimate, so text count is not used. A missing page entry
    or Docling's zero-sized placeholder means extraction for that page failed.
    """
    pages = structured.get("pages")
    if not isinstance(pages, dict):
        return list(range(1, rendered_page_count + 1))

    missing: list[int] = []
    for page_number in range(1, rendered_page_count + 1):
        page = pages.get(str(page_number), pages.get(page_number))
        size = page.get("size") if isinstance(page, dict) else None
        width = size.get("width", 0) if isinstance(size, dict) else 0
        height = size.get("height", 0) if isinstance(size, dict) else 0
        if (
            not isinstance(width, (int, float))
            or not isinstance(height, (int, float))
            or width <= 0
            or height <= 0
        ):
            missing.append(page_number)
    return missing


def page_failures(page_numbers: list[int]) -> list[dict[str, object]]:
    """Build contract-compatible failures for pages rejected by quality checks."""
    return [
        {
            "page_number": page_number,
            "stage": "extract",
            "reason": "Parser did not produce a valid page representation.",
            "resolution": "Page render was preserved; multimodal retry is required.",
        }
        for page_number in page_numbers
    ]
