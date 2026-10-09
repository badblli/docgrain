"""TIFF (multi-page), BMP and WEBP through Docgrain's image rules (WP106).

Each image or TIFF page is decoded and prepared exactly like PNG/JPEG (EXIF orientation, pixel
budget, white background, full-page OCR) and read by Docling as that prepared PNG. Boxes keep
pointing at original encoded pixels. A multi-page TIFF is addressed as its pages stacked top to
bottom ("vertical-stack-v1"): one image_region frame of max(width) x sum(heights) pixels whose page
offsets are recorded in processing_options["multi_frame"], so every box stays exact and unique
without a new canonical locator field.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from typing import Any

from docgrain_domain.source_format import SourceFormat
from PIL import Image

from .image_geometry import prepare_image
from .structural import ParseIssue, StructuralItem, StructuralParseResult

MIME = {"tiff": "image/tiff", "bmp": "image/bmp", "webp": "image/webp", "png": "image/png", "jpeg": "image/jpeg"}
LAYOUT = "vertical-stack-v1"


def frames(data: bytes) -> list[bytes]:
    """Single images unchanged; each TIFF page as a lossless single-page TIFF with its own tags."""
    with Image.open(BytesIO(data)) as image:
        count = getattr(image, "n_frames", 1)
        if count == 1:
            return [data]
        pages = []
        for index in range(count):
            image.seek(index)
            orientation = image.getexif().get(274, 1)
            buffer = BytesIO()
            image.copy().save(buffer, format="TIFF", compression="tiff_lzw", tiffinfo={274: orientation})
            pages.append(buffer.getvalue())
        return pages


def _relabel(result: StructuralParseResult, fmt: SourceFormat, original: bytes) -> StructuralParseResult:
    result.source_format = fmt
    result.issues = [replace(issue, source_format=fmt) for issue in result.issues]
    for item in result.items:
        if item.anchor == "original-image":
            item.asset_bytes = original
            item.asset_mime = MIME[fmt.value]
    result.processing_options["image_container"] = fmt.value
    return result


def _stack(locator: dict | None, offset: int, size: tuple[int, int], total: tuple[int, int]) -> dict | None:
    if not locator or locator.get("kind") != "image_region":
        return locator
    (width, height), (stack_width, stack_height) = size, total
    box = locator["bbox"]
    x, y = box["x"] * width / stack_width, (offset + box["y"] * height) / stack_height
    w = min(box["width"] * width / stack_width, 1 - x)
    h = min(box["height"] * height / stack_height, 1 - y)
    return {"kind": "image_region", "width_px": stack_width, "height_px": stack_height, "exif_orientation": 1,
            "bbox": {"x": x, "y": y, "width": w, "height": h}}


def _concatenate(results: list[StructuralParseResult]) -> bytes | None:
    documents = [r.legacy_json for r in results if r.legacy_json]
    if not documents:
        return None
    try:
        from docling_core.types.doc import DoclingDocument

        merged = DoclingDocument.concatenate([DoclingDocument.model_validate_json(d) for d in documents])
        return json.dumps(merged.export_to_dict(), ensure_ascii=False).encode()
    except Exception:  # noqa: BLE001 - keep page one rather than lose the parser artifact.
        return documents[0]


def _merge(results: list[StructuralParseResult], metadata: list[dict], fmt: SourceFormat,
           original: bytes) -> StructuralParseResult:
    sizes = [(m["width_px"], m["height_px"]) for m in metadata]
    total = (max(w for w, _ in sizes), sum(h for _, h in sizes))
    offsets = [sum(h for _, h in sizes[:index]) for index in range(len(sizes))]
    items: list[StructuralItem] = []
    issues: list[ParseIssue] = []
    cells: list[dict] = []
    expected, processed = [], []
    for number, (result, offset, size) in enumerate(zip(results, offsets, sizes, strict=True), start=1):
        area = f"frame:{number}"
        expected.append(area)
        if "image" in result.processed_areas:
            processed.append(area)
        for issue in result.issues:
            issues.append(replace(issue, source_format=fmt,
                                  location=area if issue.location == "image" else issue.location))
        if result.status == "failed":
            issues.append(ParseIssue("frame_failed", "structural_parse", fmt, area, None,
                                     "TIFF sayfası okunamadı", "page"))
            continue
        for item in result.items:
            if item.anchor == "original-image":
                continue
            item.anchor = f"frame:{number}:{item.anchor}"
            item.locator = _stack(item.locator, offset, size, total)
            for row in item.cells:
                for cell in row:
                    if isinstance(cell, dict) and "locator" in cell:
                        cell["locator"] = _stack(cell["locator"], offset, size, total)
            items.append(item)
        for cell in result.source_metadata.get("ocr_cells", []):
            cells.append({**cell, "frame": number, "locator": _stack(cell.get("locator"), offset, size, total)})
    whole = {"kind": "image_region", "width_px": total[0], "height_px": total[1], "exif_orientation": 1,
             "bbox": {"x": 0, "y": 0, "width": 1, "height": 1}}
    items.append(StructuralItem("picture", "original-image", whole, asset_bytes=original, asset_mime=MIME[fmt.value]))
    first = next((r for r in results if r.status != "failed"), results[0])
    options: dict[str, Any] = dict(first.processing_options)
    options["image_container"] = fmt.value
    options["image_preparation"] = metadata
    options["multi_frame"] = {"layout": LAYOUT, "width_px": total[0], "height_px": total[1],
                              "frames": [{"frame": n, "x": 0, "y": o, "width": s[0], "height": s[1]}
                                         for n, (o, s) in enumerate(zip(offsets, sizes, strict=True), start=1)]}
    failed = all(r.status == "failed" for r in results)
    merged = StructuralParseResult(fmt, first.parser, first.parser_version,
                                   "failed" if failed else ("partial" if issues else "complete"),
                                   items, expected, processed, issues, processing_options=options)
    merged.source_metadata = {
        "pages": {str(n): r.source_metadata.get("pages", {}) for n, r in enumerate(results, start=1)},
        "ocr_cells": cells, "image_preparation": metadata,
        "raster_preparation": [e for r in results for e in r.source_metadata.get("raster_preparation", [])],
        "docling_confidence": [r.source_metadata.get("docling_confidence") for r in results],
    }
    merged.legacy_markdown = b"\n\n".join(r.legacy_markdown for r in results if r.legacy_markdown) or None
    merged.legacy_json = _concatenate(results)
    return merged


def parse_image(data: bytes, fmt: SourceFormat,
                convert: Callable[[bytes, dict], StructuralParseResult]) -> StructuralParseResult:
    """``convert(prepared_png, metadata)`` runs the existing PNG image route for one page."""
    pages = frames(data)
    results, metadata = [], []
    for number, page in enumerate(pages, start=1):
        prepared, meta = prepare_image(page)
        if len(pages) > 1:
            meta.update(frame=number, frame_count=len(pages), frame_sha256=meta["source_sha256"],
                        source_sha256=sha256(data).hexdigest())
        metadata.append(meta)
        results.append(convert(prepared, meta))
    if len(pages) == 1:
        return _relabel(results[0], fmt, data)
    return _merge(results, metadata, fmt, data)
