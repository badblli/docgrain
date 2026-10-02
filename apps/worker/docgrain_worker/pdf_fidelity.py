"""Compare native words with ruled cells; ambiguous grids stay explicit review gaps."""

from __future__ import annotations

import pymupdf
from docgrain_domain.source_format import SourceFormat

from .pdf_geometry import normalized_pdf_box
from .structural import StructuralItem, _issue


def _raw(rect, page_number):
    return {"kind": "pdf_native", "page_number": page_number, "rect": list(rect)}


def ruled_cells(page, found):
    # find_tables can insert slots which are covered by the same physical cell in every row.
    # Keep physical cells; do not turn those phantom slots into extra semantic columns.
    keep = [
        c
        for c in range(found.col_count)
        if any(row.cells[c] is not None for row in found.rows)
    ]
    words = page.get_text("words")
    physical = {
        tuple(box) for row in found.rows for box in row.cells if box is not None
    }
    assignments = {box: [] for box in physical}
    excluded = {box: [] for box in physical}
    ambiguous = 0
    for word in words:
        x, y = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
        matches = [b for b in physical if b[0] < x < b[2] and b[1] < y < b[3]]
        if len(matches) == 1:
            box = matches[0]
            if (
                box[0] - 0.5 <= word[0]
                and word[2] <= box[2] + 0.5
                and box[1] - 0.5 <= word[1]
                and word[3] <= box[3] + 0.5
            ):
                assignments[box].append(word)
            else:
                # Visible clipped/overflow text is not assigned as a full word to a neighbour.
                # Preserve it for review instead of silently discarding the source diagnostic.
                excluded[box].append(word[4])
        elif len(matches) > 1:
            ambiguous += 1
    rows = []
    for r, row in enumerate(found.rows):
        cells = []
        for c in keep:
            box = row.cells[c]
            if box is None:
                cells.append(
                    {"value": "", "source_attributes": {"merge_covered": True}}
                )
                continue
            box = tuple(box)
            selected = sorted(assignments[box], key=lambda w: (w[5], w[6], w[7]))
            value = " ".join(w[4] for w in selected)
            col_span = 1
            for next_c in keep[keep.index(c) + 1 :]:
                if row.cells[next_c] is not None:
                    break
                # A covered slot is part of this physical merged cell only if its
                # next row's column edge is inside the cell's horizontal extent.
                candidates = [
                    rr.cells[next_c]
                    for rr in found.rows
                    if rr.cells[next_c] is not None
                ]
                if candidates and min(b[0] for b in candidates) < box[2] - 0.5:
                    col_span += 1
            row_span = 1
            for rr in found.rows[r + 1 :]:
                if rr.cells[c] is not None:
                    break
                ys = [b[1] for b in rr.cells if b is not None]
                if ys and min(ys) < box[3] - 0.5:
                    row_span += 1
            cells.append(
                {
                    "value": value,
                    "row_span": row_span,
                    "col_span": col_span,
                    "source_attributes": {
                        "native_words": [w[4] for w in selected],
                        "boundary_words": excluded[box],
                        "merge_covered": False,
                    },
                    "locator": _raw(box, page.number + 1),
                }
            )
        rows.append(cells)
    return rows, ambiguous


def reconcile_pdf_tables(source, items, issues, pages):
    changes = []
    with pymupdf.open(source.path) as pdf:
        for number, page in enumerate(pdf, 1):
            rotation = page.rotation
            page.set_rotation(
                0
            )  # find_tables has a different rotation convention from get_text.
            try:
                # Ignore borderless filled rectangles (e.g. highlighted text) as grid edges.
                found_tables = page.find_tables(strategy="lines_strict").tables
            except (ValueError, RuntimeError) as error:
                page.set_rotation(rotation)
                issues.append(
                    _issue(
                        SourceFormat.PDF,
                        "native_table_detection_failed",
                        str(error)[:200],
                        location=f"page:{number}",
                    )
                )
                continue
            for found in found_tables:
                rows, ambiguous = ruled_cells(page, found)
                page.set_rotation(rotation)
                if any(
                    c.get("source_attributes", {}).get("boundary_words")
                    for row in rows
                    for c in row
                ):
                    issues.append(
                        _issue(
                            SourceFormat.PDF,
                            "table_boundary_text_review",
                            "Words crossing cell borders retained as diagnostics; visible clipping needs review",
                            location=f"page:{number}",
                        )
                    )
                if not rows or not any(c["value"] for row in rows for c in row):
                    page.set_rotation(0)
                    continue  # Never replace scan/OCR content with an empty native layer.
                # Both readers' frames are mapped to the actual visible page before matching.
                native_visible = pymupdf.Rect(found.bbox) * page.rotation_matrix
                native_norm = (
                    native_visible.x0 / page.rect.width,
                    native_visible.y0 / page.rect.height,
                    native_visible.x1 / page.rect.width,
                    native_visible.y1 / page.rect.height,
                )
                matches = []
                for item in items:
                    if (
                        item.kind != "table"
                        or (item.locator or {}).get("page_number") != number
                    ):
                        continue
                    box = normalized_pdf_box(
                        item.locator.get("bbox"), item.page_size or (0, 0), page, frame=item.locator.get("frame")
                    )
                    if box:
                        a = pymupdf.Rect(
                            box.x, box.y, box.x + box.width, box.y + box.height
                        )
                        b = pymupdf.Rect(native_norm)
                        if (a & b).get_area() / max(
                            min(a.get_area(), b.get_area()), 1e-9
                        ) > 0.8:
                            matches.append(item)
                if len(matches) > 1 or ambiguous:
                    issues.append(
                        _issue(
                            SourceFormat.PDF,
                            "table_geometry_ambiguous",
                            "Native/Docling regions or word assignment are ambiguous; no correction applied",
                            location=f"page:{number}",
                        )
                    )
                    page.set_rotation(0)
                    continue
                if matches:
                    item = matches[0]
                    shape = (len(item.cells), max(map(len, item.cells), default=0))
                    native_shape = (len(rows), len(rows[0]))
                    if shape != native_shape:
                        issues.append(
                            _issue(
                                SourceFormat.PDF,
                                "table_grid_conflict",
                                f"Docling {shape} vs native {native_shape}; no shape-changing overwrite",
                                location=f"page:{number}",
                                item_ref=item.anchor,
                            )
                        )
                        page.set_rotation(0)
                        continue
                    # Mixed tables must retain OCR in image-only cells; alternate native
                    # grid is a diagnostic until reconciliation can prove both layers.
                    if item.text_origin in {"ocr", "mixed"}:
                        issues.append(
                            _issue(
                                SourceFormat.PDF,
                                "mixed_table_needs_review",
                                "Native grid cannot overwrite OCR/mixed cells",
                                location=f"page:{number}",
                                item_ref=item.anchor,
                            )
                        )
                        page.set_rotation(0)
                        continue
                    for r, row in enumerate(rows):
                        for c, cell in enumerate(row):
                            old = item.cells[r][c]
                            attrs = cell["source_attributes"]
                            attrs["parser_text"] = old.get("value")
                            if cell["value"] != old.get("value", ""):
                                changes.append(
                                    {
                                        "anchor": item.anchor,
                                        "row": r,
                                        "column": c,
                                        "parser_text": old.get("value"),
                                        "native_text": cell["value"],
                                        "locator": cell.get("locator"),
                                    }
                                )
                    item.cells = rows
                else:
                    locator = _raw(found.bbox, number)
                    item = StructuralItem(
                        "table",
                        f"native-table:{number}:{found.bbox}",
                        locator,
                        cells=rows,
                        page_size=(page.cropbox.width, page.cropbox.height),
                    )
                    # Remove only wholly contained standalone text; preserve other columns/pictures.
                    indices = []
                    for index, other in enumerate(items):
                        if (
                            other.kind != "paragraph"
                            or (other.locator or {}).get("page_number") != number
                        ):
                            continue
                        box = normalized_pdf_box(
                            other.locator.get("bbox"), other.page_size or (0, 0), page, frame=other.locator.get("frame")
                        )
                        if box and pymupdf.Rect(native_norm).contains(
                            pymupdf.Rect(
                                box.x, box.y, box.x + box.width, box.y + box.height
                            )
                        ):
                            indices.append(index)
                    at = (
                        min(indices)
                        if indices
                        else next(
                            (
                                i
                                for i, v in enumerate(items)
                                if (v.locator or {}).get("page_number", 0) > number
                            ),
                            len(items),
                        )
                    )
                    for index in reversed(indices):
                        items.pop(index)
                    items.insert(at, item)
                    issues.append(
                        _issue(
                            SourceFormat.PDF,
                            "native_table_recovered",
                            "Docling omitted ruled native table; cells recovered with individual evidence",
                            location=f"page:{number}",
                        )
                    )
                page.set_rotation(0)
            page.set_rotation(rotation)
    if changes:
        issues.append(
            _issue(
                SourceFormat.PDF,
                "native_table_reconciled",
                "Native word-to-ruled-cell mapping differs from parser; original parser text retained for source review",
                impact="table",
            )
        )
    return {"strategy": "ruled-native-word-centers-v1", "changes": changes}
