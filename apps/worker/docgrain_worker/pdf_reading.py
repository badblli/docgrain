"""Geometry order and exact-token splitting of accidentally joined native columns."""

from collections import Counter
import re

import pymupdf
from docgrain_domain.source_format import SourceFormat

from .pdf_geometry import normalized_pdf_box
from .structural import StructuralItem, _issue


def source_rect(item, page):
    loc = item.locator or {}
    if loc.get("kind") == "pdf_native":
        return pymupdf.Rect(loc["rect"])
    box = normalized_pdf_box(
        loc.get("bbox"), item.page_size or (0, 0), page, frame=loc.get("frame")
    )
    if box is None:
        return None
    visible = pymupdf.Rect(
        box.x * page.rect.width,
        box.y * page.rect.height,
        (box.x + box.width) * page.rect.width,
        (box.y + box.height) * page.rect.height,
    )
    return visible * page.derotation_matrix


def _xy_order(entries):
    if len(entries) < 2:
        return entries
    for axis in (1, 0):  # Separate full-width bands, then columns in each band.
        intervals = sorted((r[axis], r[axis + 2]) for _, r in entries)
        end = intervals[0][1]
        gaps = []
        for lo, hi in intervals[1:]:
            if lo - end > 4:
                gaps.append((lo - end, (lo + end) / 2))
            end = max(end, hi)
        if gaps:
            split = max(gaps)[1]
            left = [e for e in entries if e[1][axis + 2] < split]
            right = [e for e in entries if e[1][axis] > split]
            if left and right and len(left) + len(right) == len(entries):
                return _xy_order(left) + _xy_order(right)
    return sorted(entries, key=lambda e: (e[1].y0, e[1].x0))


def reconcile_reading(source, items, issues):
    diagnostics = []

    def tokens(text):
        return Counter(re.findall(r"\S+", text))

    with pymupdf.open(source.path) as pdf:
        ordered = []
        for number, page in enumerate(pdf, 1):
            group = [i for i in items if (i.locator or {}).get("page_number") == number]
            blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
            tables = [source_rect(i, page) for i in group if i.kind == "table"]
            blocks = [
                b
                for b in blocks
                if not any(r and r.contains(pymupdf.Rect(b[:4])) for r in tables)
            ]
            text_items = [
                i
                for i in group
                if i.kind in {"paragraph", "heading", "list_item"}
                and i.text_origin == "native"
            ]
            edges = {}
            for idx, item in enumerate(text_items):
                rect = source_rect(item, page)
                if not rect:
                    continue
                edges[idx] = [
                    j
                    for j, b in enumerate(blocks)
                    if (rect & pymupdf.Rect(b[:4])).get_area()
                    / max(min(rect.get_area(), pymupdf.Rect(b[:4]).get_area()), 1e-9)
                    > 0.2
                ]
            seen = set()
            for idx in edges:
                if idx in seen:
                    continue
                component = {idx}
                native = set(edges[idx])
                changed = True
                while changed:
                    changed = False
                    for k, values in edges.items():
                        if k not in component and native.intersection(values):
                            component.add(k)
                            native.update(values)
                            changed = True
                seen.update(component)
                if len(native) < 2 or not any(len(edges[k]) > 1 for k in component):
                    continue
                old = [text_items[k] for k in sorted(component)]
                source_blocks = [blocks[j] for j in sorted(native)]
                if tokens(" ".join(i.text for i in old)) != tokens(
                    " ".join(b[4] for b in source_blocks)
                ):
                    issues.append(
                        _issue(
                            SourceFormat.PDF,
                            "column_text_conflict",
                            "Native blocks and parser text differ; no automatic column split",
                            location=f"page:{number}",
                        )
                    )
                    continue
                for item in old:
                    group.remove(item)
                for b in source_blocks:
                    group.append(
                        StructuralItem(
                            "paragraph",
                            f"native-block:{number}:{b[5]}",
                            {
                                "kind": "pdf_native",
                                "page_number": number,
                                "rect": list(b[:4]),
                            },
                            text=b[4].rstrip("\n"),
                            page_size=(page.cropbox.width, page.cropbox.height),
                        )
                    )
                diagnostics.append(
                    {
                        "page": number,
                        "parser_blocks": [
                            {"anchor": i.anchor, "text": i.text} for i in old
                        ],
                        "native_blocks": [
                            {"rect": list(b[:4]), "text": b[4]} for b in source_blocks
                        ],
                    }
                )
                issues.append(
                    _issue(
                        SourceFormat.PDF,
                        "native_columns_recovered",
                        "Merged parser columns split using exact native token parity; hierarchy/order needs source review",
                        location=f"page:{number}",
                    )
                )
            entries = [(i, source_rect(i, page)) for i in group]
            valid = [e for e in entries if e[1] is not None]
            sequence = [i for i, _ in _xy_order(valid)] + [
                i for i, r in entries if r is None
            ]
            if sequence != group:
                diagnostics.append(
                    {
                        "page": number,
                        "parser_order": [i.anchor for i in group],
                        "geometry_order": [i.anchor for i in sequence],
                    }
                )
            ordered.extend(sequence)
        ordered.extend(i for i in items if not (i.locator or {}).get("page_number"))
        items[:] = ordered
    return {
        "strategy": "native-block-exact-token+xy-cut-v1",
        "diagnostics": diagnostics,
    }
