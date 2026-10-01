"""Docling PDF coordinates to visible, rotated PyMuPDF page coordinates."""

from __future__ import annotations

from typing import Any

import pymupdf
from docgrain_domain.canonical import NormalizedBox


def normalized_pdf_box(raw: dict[str, Any] | None, docling_size: tuple[float, float],
                       page: pymupdf.Page) -> NormalizedBox | None:
    if not raw:
        return None
    width, height = docling_size
    if width <= 0 or height <= 0:
        return None
    try:
        left, right = float(raw["l"]), float(raw["r"])
        top, bottom = float(raw["t"]), float(raw["b"])
        if raw.get("coord_origin") == "BOTTOMLEFT":
            top, bottom = height - top, height - bottom
        elif raw.get("coord_origin") != "TOPLEFT":
            return None
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            return None
        crop = page.cropbox
        media = page.mediabox
        visible = page.rect
        def same(a, b):
            return abs(a - b) <= 1.0
        crop_frame = same(width, crop.width) and same(height, crop.height)
        media_frame = same(width, media.width) and same(height, media.height)
        rotated_frame = same(width, visible.width) and same(height, visible.height)
        if crop_frame:
            points = [pymupdf.Point(x, y) * page.rotation_matrix
                      for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))]
        elif media_frame:
            origin = page.cropbox_position
            points = [pymupdf.Point(x - origin.x, y - origin.y) * page.rotation_matrix
                      for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))]
        elif rotated_frame:
            points = [pymupdf.Point(x, y) for x, y in
                      ((left, top), (right, top), (right, bottom), (left, bottom))]
        else:
            return None
        x0, x1 = min(p.x for p in points), max(p.x for p in points)
        y0, y1 = min(p.y for p in points), max(p.y for p in points)
        if x0 < -0.01 or y0 < -0.01 or x1 > visible.width + 0.01 or y1 > visible.height + 0.01:
            return None
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(visible.width, x1), min(visible.height, y1)
        return NormalizedBox(x=x0 / visible.width, y=y0 / visible.height,
                             width=(x1 - x0) / visible.width, height=(y1 - y0) / visible.height)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
