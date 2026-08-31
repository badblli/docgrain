"""Primary per-page multimodal extraction through Gemini Vision."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class VisionRegion(BaseModel):
    """One visually grounded region; coordinates are normalized to 0..1000."""

    kind: Literal[
        "title",
        "heading",
        "paragraph",
        "list",
        "table",
        "image",
        "chart",
        "diagram",
        "form",
        "caption",
        "other",
    ]
    box_2d: list[int] = Field(min_length=4, max_length=4)
    text: str
    markdown: str
    caption: str | None
    relationships: list[str]
    content_origin: Literal["visible_text", "visual_description", "inference"]


class VisionPage(BaseModel):
    page_number: int = Field(ge=1)
    language: str
    page_title: str | None
    markdown: str
    regions: list[VisionRegion]
    table_count: int = Field(ge=0)
    asset_count: int = Field(ge=0)


class PageExtractor(Protocol):
    def extract(self, image_path: Path, page_number: int) -> VisionPage: ...


PAGE_PROMPT = """Read this document page as evidence, not as a screenshot to summarize.
Preserve all visible text, heading hierarchy, lists, tables, forms and captions.
Identify images, charts and diagrams and describe what they communicate.
Keep relationships between captions and visuals, labels and values, and headings and
their content. Distinguish literal visible text from a visual description or an
inference. Use normalized 0..1000 [ymin, xmin, ymax, xmax] boxes. Do not invent content
that is not visible. Produce the complete page in reading order.
"""


class GeminiPageExtractor:
    """Thin SDK adapter; imported lazily so fixture tests need no credential."""

    def __init__(self, api_key: str, model: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def extract(self, image_path: Path, page_number: int) -> VisionPage:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                types.Part.from_bytes(
                    data=image_path.read_bytes(), mime_type="image/png"
                ),
                f"Document page number: {page_number}.\n{PAGE_PROMPT}",
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=VisionPage.model_json_schema(),
            ),
        )
        if not response.text:
            raise ValueError("Gemini returned an empty page extraction")
        page = VisionPage.model_validate_json(response.text)
        return page.model_copy(update={"page_number": page_number})


def extract_pages(
    pages: Iterable[tuple[int, Path]],
    extractor: PageExtractor,
    *,
    max_workers: int = 4,
    attempts: int = 3,
    retry_delay: Callable[[int], None] | None = None,
) -> tuple[dict[int, VisionPage], dict[int, str]]:
    """Extract pages concurrently with bounded per-page retries."""
    delay = retry_delay or (lambda attempt: time.sleep(2 ** (attempt - 1)))

    def run(page_number: int, image_path: Path) -> VisionPage:
        error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return extractor.extract(image_path, page_number)
            except Exception as exc:  # noqa: BLE001 - provider errors are retried.
                error = exc
                if attempt < attempts:
                    delay(attempt)
        raise RuntimeError(str(error) if error else "page extraction failed")

    results: dict[int, VisionPage] = {}
    failures: dict[int, str] = {}
    page_list = list(pages)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(run, page_number, image_path): page_number
            for page_number, image_path in page_list
        }
        for future in as_completed(futures):
            page_number = futures[future]
            try:
                results[page_number] = future.result()
            except Exception as exc:  # noqa: BLE001 - persisted as page failure.
                failures[page_number] = str(exc)[:1000]
    return results, failures
