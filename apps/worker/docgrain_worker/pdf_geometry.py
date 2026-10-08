"""Docling PDF coordinates to visible, rotated PyMuPDF page coordinates."""

from __future__ import annotations

import math
from typing import Any

import pymupdf
from docgrain_domain.canonical import NormalizedBox


def normalized_pdf_box(raw: dict[str, Any] | None, docling_size: tuple[float, float],
                       page: pymupdf.Page, *, frame: str | None = None,
                       tolerance_points: float = 0) -> NormalizedBox | None:
    if not math.isfinite(tolerance_points) or not 0 <= tolerance_points <= 5:
        raise ValueError("bbox tolerance must be between 0 and 5 PDF points")
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
        if not all(math.isfinite(v) for v in (left, right, top, bottom, width, height)):
            return None
        if tolerance_points:
            if not (-tolerance_points <= left < right <= width + tolerance_points
                    and -tolerance_points <= top < bottom <= height + tolerance_points):
                return None
            left, top = max(0, left), max(0, top)
            right, bottom = min(width, right), min(height, bottom)
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
        if frame == "visible" and rotated_frame:
            points = [pymupdf.Point(x, y) for x, y in
                      ((left, top), (right, top), (right, bottom), (left, bottom))]
        elif frame == "visible":
            return None
        elif crop_frame:
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
        tolerance = max(0.01, tolerance_points)
        if x0 < -tolerance or y0 < -tolerance or x1 > visible.width + tolerance or y1 > visible.height + tolerance:
            return None
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(visible.width, x1), min(visible.height, y1)
        if x0 >= x1 or y0 >= y1:
            return None
        return NormalizedBox(x=x0 / visible.width, y=y0 / visible.height,
                             width=(x1 - x0) / visible.width, height=(y1 - y0) / visible.height)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
