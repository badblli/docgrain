"""Format-neutral structural extraction; Docling never crosses this boundary."""

# Karar 18 (2026-10-08): _pdf_missing_tables, _docx_paths, eski _xlsx_items/_tag_ocr ve native fidelity yolu artık kullanılmıyor; okuma Docling + Tesseract ile yapılıyor.
# Eski kod silinmedi, başvuru için duruyor: unused/structural_before_docling.py
# (ayrıca native_office.py, pdf_fidelity.py, pdf_reading.py, vision.py — hiçbiri import edilmiyor).

from __future__ import annotations

import base64
import importlib.metadata
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from docgrain_domain.source_format import SourceFormat, verify_format


@dataclass(frozen=True)
class VerifiedSource:
    path: Path
    content_sha256: str
    byte_size: int


@dataclass(frozen=True)
class ParseIssue:
    code: str
    stage: str
    source_format: SourceFormat
    location: str | None
    item_ref: str | None
    reason: str
    impact: str


@dataclass
class StructuralItem:
    kind: Literal["heading", "paragraph", "list_item", "table", "picture", "chart"]
    anchor: str
    locator: dict[str, Any] | None
    text: str = ""
    level: int = 1
    cells: list[list[dict[str, Any]]] = field(default_factory=list)
    asset_path: str | None = None
    asset_bytes: bytes | None = None
    asset_mime: str | None = None
    page_size: tuple[float, float] | None = None
    line_range: tuple[int, int] | None = None
    text_origin: Literal["native", "ocr", "mixed"] = "native"
    ocr_confidence: float | None = None
    source_data: dict[str, Any] | None = None
    field_locators: dict[str, dict] = field(default_factory=dict)


@dataclass
class StructuralParseResult:
    source_format: SourceFormat
    parser: str
    parser_version: str
    status: Literal["complete", "partial", "failed"]
    items: list[StructuralItem]
    expected_areas: list[str]
    processed_areas: list[str]
    issues: list[ParseIssue]
    source_metadata: dict[str, Any] = field(default_factory=dict)
    processing_options: dict[str, Any] = field(default_factory=dict)
    legacy_markdown: bytes | None = None
    legacy_json: bytes | None = None
    reading_profile: dict[str, Any] | None = None
    docling_artifact_uri: str | None = None
    page_images: dict[int, bytes] = field(default_factory=dict)

    @property
    def coverage(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return {
            "expected_areas": self.expected_areas,
            "processed_areas": self.processed_areas,
            "skipped_areas": sorted(set(self.expected_areas) - set(self.processed_areas)),
            "item_counts": counts,
            "status": self.status,
        }


def _issue(fmt: SourceFormat, code: str, reason: str, *, location: str | None = None,
           item_ref: str | None = None, impact: str = "item") -> ParseIssue:
    return ParseIssue(code, "structural_parse", fmt, location, item_ref, reason, impact)


def _paragraphs(text: str) -> list[tuple[int, int, str, str, int, int]]:
    """Return exact paragraph spans and one-based inclusive line ranges."""
    result: list[tuple[int, int, str, str, int, int]] = []
    offset = 0
    paragraph_start: int | None = None
    paragraph_end = 0
    first_line = 0
    last_line = 0
    def flush() -> None:
        nonlocal paragraph_start
        if paragraph_start is not None:
            result.append((paragraph_start, paragraph_end, "paragraph",
                           text[paragraph_start:paragraph_end], first_line, last_line))
            paragraph_start = None
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        visible = line.rstrip("\r\n")
        if visible.strip():
            start = offset + len(visible) - len(visible.lstrip())
            end = offset + len(visible.rstrip())
            value = text[start:end]
            if re.match(r"^#{1,6} +\S", value):
                flush()
                result.append((start, end, "heading", value, line_number, line_number))
            else:
                if paragraph_start is None:
                    paragraph_start = start
                    first_line = line_number
                paragraph_end = end
                last_line = line_number
        else:
            flush()
        offset += len(line)
    flush()
    return result


def _txt(source: VerifiedSource) -> StructuralParseResult:
    data = source.path.read_bytes()
    text = data.decode("utf-8-sig", errors="strict")
    items = [StructuralItem(kind=kind, anchor=f"chars:{start}:{end}",
                            locator={"kind": "text_span", "start": start, "end": end},
                            text=value, level=len(value) - len(value.lstrip("#")) if kind == "heading" else 1,
                            line_range=(first_line, last_line))
             for start, end, kind, value, first_line, last_line in _paragraphs(text)]
    line_count = len(text.splitlines())
    return StructuralParseResult(SourceFormat.TXT, "deterministic-text", "1", "complete", items,
                                 [f"line:{n}" for n in range(1, line_count + 1)],
                                 [f"line:{n}" for n in range(1, line_count + 1)], [],
                                 {"encoding": "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8",
                                  "line_count": line_count})


def _docling(source: VerifiedSource, fmt: SourceFormat, *,
             image_metadata: dict | None = None,
             profile: str = "C_tesseract", remote: Any = None) -> StructuralParseResult:
    from .docling_profiles import (
        build_converter,
        confidence_report,
        default_full_page,
        identity,
        safe_options,
    )

    is_image = fmt in (SourceFormat.PNG, SourceFormat.JPEG)
    ocr_enabled = fmt is SourceFormat.PDF or is_image
    full_page = default_full_page(source, fmt) if profile == "C_tesseract" else False
    from .image_budget import render_settings
    images_scale, raster_budget = render_settings(source, fmt, image_metadata)
    raster_events = []
    converter, input_format = build_converter(fmt, profile=profile, full_page=full_page,
                                             remote=remote, images_scale=images_scale,
                                             raster_events=raster_events)
    processing_options = {
        "pipeline": safe_options(converter.format_to_options[input_format].pipeline_options.model_dump(mode="json")),
        "adapter_version": "docling-2", "canonical_schema_version": "0.6.0",
        "formula_evaluation": False, "ocr_routing": "file-text-layer-v1",
        "xlsx_display_format": "number-date-percent-v1",
    }
    if raster_budget:
        processing_options["image_budget"] = raster_budget
    if ocr_enabled or is_image:
        if ocr_enabled:
            from .docling_models import LAYOUT, MODELS, TABLEFORMER

            models = MODELS if profile in {"D_fullpage", "E_vlm"} else (LAYOUT, TABLEFORMER)
            processing_options["docling_models"] = {m.repo_id: m.revision for m in models}
            processing_options["pipeline"]["artifacts_path"] = "pinned-docling-models"
            from .ocr import verified_profile
            if profile == "B_docling":
                processing_options["ocr_profile"] = verified_profile()
                processing_options["ocr_profile"]["recognition_threshold"] = 0.5
            else:
                import subprocess
                probe = subprocess.run(["tesseract", "--version"], capture_output=True,
                                       text=True, check=True, timeout=15)
                tesseract_version = (probe.stdout.strip() or probe.stderr.strip()).splitlines()[0]
                processing_options["ocr_profile"] = {"engine": "tesseract", "version": tesseract_version,
                                                     "languages": ["tur", "eng", "deu", "rus"]}
            # Installation path is operational, not part of semantic configuration identity.
            if profile == "B_docling":
                processing_options["pipeline"]["ocr_options"]["model_storage_directory"] = "pinned-checkpoints"
        if image_metadata:
            processing_options["image_preparation"] = image_metadata
    converted = converter.convert(source.path, raises_on_error=False)
    version = importlib.metadata.version("docling")
    if converted.document is None:
        return StructuralParseResult(fmt, "docling", version, "failed", [], [], [],
                                     [_issue(fmt, "conversion_failed", "Docling conversion failed" if profile == "E_vlm" else str(converted.errors)[:1000], impact="document")],
                                     processing_options=processing_options)
    raw = converted.document.export_to_dict()
    pages = raw.get("pages", {})
    issues: list[ParseIssue] = []
    for event in raster_events:
        # Image inputs: capping Docling's 3x OCR upscale is not a loss against the source
        # pixels; only the source downscale below is reported for them.
        if is_image and image_metadata and max(event["used_size"]) >= max(
                image_metadata["input_width_px"], image_metadata["input_height_px"]) - 1:
            continue
        issues.append(_issue(fmt, "image_downscaled",
            f"Okuma görseli küçültüldü: özgün {event['original_size']} piksel; kullanılan {event['used_size']} piksel",
            location=f"page:{event['page_number']}" if fmt is SourceFormat.PDF else "image", impact="page"))
    if image_metadata and image_metadata.get("downscaled"):
        issues.append(_issue(fmt, "image_downscaled",
            f"Görsel küçültüldü: özgün {image_metadata['width_px']}x{image_metadata['height_px']} piksel; "
            f"kullanılan {image_metadata['input_width_px']}x{image_metadata['input_height_px']} piksel",
            location="image", impact="document"))
    items: list[StructuralItem] = []
    expected: list[str] = []
    if fmt is SourceFormat.PDF:
        import pymupdf

        with pymupdf.open(source.path) as pdf:
            expected = [f"page:{number}" for number in range(1, len(pdf) + 1)]
    if is_image:
        expected = ["image"]
    processed = [f"page:{n}" for n, page in pages.items()
                 if page.get("size", {}).get("width", 0) > 0 and page.get("size", {}).get("height", 0) > 0] if fmt is SourceFormat.PDF else []
    if is_image:
        processed = ["image"] if pages.get("1", {}).get("size", {}).get("width", 0) > 0 else []
        if not processed:
            issues.append(_issue(fmt, "image_geometry_missing", "Parser image dimensions unavailable", location="image"))
    if fmt is SourceFormat.DOCX:
        expected = ["document"]
        processed = ["document"]
    if fmt is SourceFormat.XLSX:
        from openpyxl import load_workbook

        workbook = load_workbook(source.path, read_only=True)
        try:
            expected = [f"sheet:{name}" for name in workbook.sheetnames]
        finally:
            workbook.close()
        processed = [f"sheet:{g['name']}" for g in raw.get("groups", []) if g.get("label") == "sheet"]

    lookup = {entry["self_ref"]: entry for collection in ("texts", "tables", "pictures")
              for entry in raw.get(collection, [])}
    if fmt is SourceFormat.XLSX:
        items.extend(_xlsx_items(source, raw, issues))
    for ref in (_reading_refs(raw.get("body", {}), raw, lookup)
                + _reading_refs(raw.get("furniture", {}), raw, lookup)):
        item = lookup[ref]
        label = item.get("label", "")
        kind = {"section_header": "heading", "title": "heading", "list_item": "list_item",
                "table": "table", "picture": "picture"}.get(label, "paragraph")
        if fmt is SourceFormat.XLSX and kind != "picture":
            continue
        if kind == "paragraph" and not item.get("text"):
            continue
        locator = None
        page_size = None
        if fmt is SourceFormat.PDF or is_image:
            provenance = item.get("prov") or []
            if provenance:
                p = provenance[0]
                n = str(p["page_no"])
                locator = {"kind": "pdf_raw", "page_number": int(n), "bbox": p.get("bbox")}
                size = pages.get(n, {}).get("size", {})
                page_size = (float(size.get("width", 0)), float(size.get("height", 0)))
                if is_image and image_metadata:
                    from .image_geometry import image_locator
                    try:
                        locator = image_locator(p.get("bbox") or {}, page_size, image_metadata)
                    except (ValueError, KeyError):
                        locator = None
                        issues.append(_issue(fmt, "image_bbox_unresolved", "Cannot map parser geometry to original pixels", item_ref=ref))
            else:
                issues.append(_issue(fmt, "missing_bbox", "Docling item has no provenance", item_ref=ref))
        elif fmt is SourceFormat.XLSX:
            from openpyxl.utils import get_column_letter
            groups = {g["self_ref"]: g for g in raw.get("groups", [])}
            parent = groups.get((item.get("parent") or {}).get("$ref"), {})
            prov = item.get("prov") or []
            box = prov[0].get("bbox") if prov else None
            if parent.get("label") == "sheet" and box and box.get("coord_origin") == "TOPLEFT":
                row, col = int(box["t"]) + 1, int(box["l"]) + 1
                if row > 0 and col > 0:
                    locator = {"kind": "spreadsheet_range", "sheet": parent["name"],
                               "a1_range": f"{get_column_letter(col)}{row}"}
            if locator is None:
                issues.append(_issue(fmt, "image_anchor_missing", "Docling picture has no sheet anchor", item_ref=ref))
        else:
            locator = {"kind": "docx_raw", "ref": ref}
        cells: list[list[dict[str, Any]]] = []
        if kind == "table":
            cells = _docling_cells(item)
        asset_bytes = None
        asset_mime = None
        if kind == "picture":
            image = item.get("image") or {}
            uri = image.get("uri", "")
            if uri.startswith("data:") and ";base64," in uri:
                try:
                    asset_bytes = base64.b64decode(uri.split(",", 1)[1], validate=True)
                    asset_mime = image.get("mimetype") or uri[5:].split(";", 1)[0]
                except (ValueError, base64.binascii.Error):
                    pass
            if not asset_bytes:
                issues.append(_issue(fmt, "unextracted_picture", "Picture has no binary asset", item_ref=ref))
        items.append(StructuralItem(kind=kind, anchor=ref, locator=locator, text=item.get("text", ""),
                                    level=int(item.get("level", 1)), cells=cells, page_size=page_size,
                                    asset_bytes=asset_bytes, asset_mime=asset_mime))
    ocr_cells = _bind_ocr_provenance(converted, raw, items, fmt, issues, image_metadata) if ocr_enabled else []
    for area in expected:
        if fmt is SourceFormat.PDF and area not in processed:
            issues.append(_issue(fmt, "missing_page", "Docling page geometry is unavailable", location=area, impact="page"))
    if is_image:
        # Always preserve the exact original binary independently of Docling picture detection.
        original = source.path.read_bytes()
        locator = {"kind": "image_region", **{k: image_metadata[k] for k in ("width_px", "height_px", "exif_orientation")},
                   "bbox": {"x": 0, "y": 0, "width": 1, "height": 1}}
        items.append(StructuralItem("picture", "original-image", locator,
            asset_bytes=original, asset_mime="image/png" if fmt is SourceFormat.PNG else "image/jpeg"))
    if str(converted.status).lower().endswith("partial_success"):
        issues.append(_issue(fmt, "docling_partial", str(converted.errors)[:1000], impact="document"))
    status = "partial" if issues else "complete"
    result = StructuralParseResult(fmt, "docling", version, status, items, expected, processed, issues,
                                   {"docling_status": str(converted.status), "pages": pages},
                                   processing_options=processing_options)
    result.source_metadata["raster_preparation"] = raster_events
    if ocr_enabled or is_image:
        result.source_metadata.update({"ocr_cells": ocr_cells, "image_preparation": image_metadata})
    result.reading_profile = identity(profile, processing_options, remote=remote)
    report = confidence_report(converted)
    if report is not None:
        from .quality import confidence_issues
        result.source_metadata["docling_confidence"] = report
        issues.extend(confidence_issues(report, fmt))
        result.status = "partial" if issues else "complete"
    import json
    result.legacy_markdown = converted.document.export_to_markdown().encode()
    result.legacy_json = json.dumps(raw, ensure_ascii=False).encode()
    if fmt is SourceFormat.PDF:
        from io import BytesIO
        for page in converted.pages:
            image = getattr(page, "image", None)
            if image is not None:
                buffer = BytesIO()
                # Docling's Page.image is a PIL image; ImageRef-style objects wrap it in pil_image.
                getattr(image, "pil_image", image).save(buffer, format="PNG")
                result.page_images[page.page_no] = buffer.getvalue()
    if profile == "E_vlm":
        from .docling_profiles import run_hard_page_vlm
        run_hard_page_vlm(source, result, remote)
    return result


def _bind_ocr_provenance(converted, raw: dict, items: list[StructuralItem], fmt: SourceFormat,
             issues: list[ParseIssue], image_metadata: dict | None) -> list[dict]:
    """Bind literal OCR cells/scores to content; scores never certify source acceptance."""
    from docling_core.types.doc import BoundingBox

    from .image_geometry import image_locator

    page_cells = {}
    literals = []
    pages = raw.get("pages", {})
    for page in converted.pages:
        cells = list(page.cells)
        page_cells[page.page_no] = cells
        ocr = [c for c in cells if c.from_ocr]
        area = f"page:{page.page_no}" if fmt is SourceFormat.PDF else "image"
        if ocr:
            issues.append(_issue(fmt, "ocr_needs_review", "OCR transcription is unreviewed, regardless of recognition score", location=area, impact="page"))
        for cell in ocr:
            box = cell.rect.to_bounding_box().model_dump(mode="json")
            locator = {"kind": "pdf_raw", "page_number": page.page_no, "bbox": box}
            if image_metadata:
                size = pages[str(page.page_no)]["size"]
                locator = image_locator(box, (size["width"], size["height"]), image_metadata)
            literals.append({"text": cell.text, "original_text": cell.orig, "confidence": cell.confidence, "locator": locator})

    def tag(box, cells, height):
        if not box:
            return "native", None
        target = BoundingBox.model_validate(box)
        matching = []
        for cell in cells:
            rect = cell.rect.to_bounding_box()
            if rect.coord_origin != target.coord_origin:
                rect = rect.to_bottom_left_origin(height) if target.coord_origin.value == "BOTTOMLEFT" else rect.to_top_left_origin(height)
            if target.intersection_area_with(rect) / max(rect.area(), 1e-9) >= 0.5:
                matching.append(cell)
        ocr = [c for c in matching if c.from_ocr]
        if not ocr:
            return "native", None
        return ("mixed" if len(ocr) < len(matching) else "ocr"), min(c.confidence for c in ocr)

    lookup = {entry["self_ref"]: entry for collection in ("texts", "tables", "pictures") for entry in raw.get(collection, [])}
    for item in items:
        if item.kind in {"picture", "chart"}:
            continue
        entry = lookup.get(item.anchor, {})
        prov = entry.get("prov") or []
        if not prov:
            continue
        number = prov[0]["page_no"]
        height = pages[str(number)]["size"]["height"]
        cells = page_cells.get(number, [])
        item.text_origin, item.ocr_confidence = tag(prov[0].get("bbox"), cells, height)
        if item.kind == "table":
            for cell in entry.get("data", {}).get("table_cells", []):
                row, col = cell["start_row_offset_idx"], cell["start_col_offset_idx"]
                if row < len(item.cells) and col < len(item.cells[row]):
                    origin, confidence = tag(cell.get("bbox"), cells, height)
                    mapped = item.cells[row][col]
                    mapped.update({"text_origin": origin, "ocr_confidence": confidence})
                    if cell.get("bbox"):
                        mapped["locator"] = {"kind": "pdf_raw", "page_number": number, "bbox": cell["bbox"]}
                        if image_metadata:
                            mapped["locator"] = image_locator(cell["bbox"], item.page_size, image_metadata)
    return literals


def _reading_refs(body: dict[str, Any], raw: dict[str, Any], lookup: dict[str, Any]) -> list[str]:
    groups = {g["self_ref"]: g for g in raw.get("groups", [])}
    result: list[str] = []
    def walk(ref: str) -> None:
        if ref in lookup:
            result.append(ref)
            for child in lookup[ref].get("children", []):
                walk(child["$ref"])
        elif ref in groups:
            for child in groups[ref].get("children", []):
                walk(child["$ref"])
    for child in body.get("children", []):
        walk(child["$ref"])
    return result


def _docling_cells(item: dict[str, Any]) -> list[list[dict[str, Any]]]:
    data = item.get("data", {})
    rows = [[{"value": ""} for _ in range(data.get("num_cols", 0))]
            for _ in range(data.get("num_rows", 0))]
    for cell in data.get("table_cells", []):
        r, c = cell["start_row_offset_idx"], cell["start_col_offset_idx"]
        if r < len(rows) and c < len(rows[r]):
            rows[r][c] = {"value": cell.get("text", ""), "row_span": cell.get("row_span", 1),
                          "col_span": cell.get("col_span", 1)}
    return rows


def _xlsx_items(source: VerifiedSource, raw: dict[str, Any], issues: list[ParseIssue]) -> list[StructuralItem]:
    from openpyxl import load_workbook
    workbook = load_workbook(source.path, read_only=False, data_only=False)
    cached = load_workbook(source.path, read_only=False, data_only=True)
    groups = {g["self_ref"]: g["name"] for g in raw.get("groups", []) if g.get("label") == "sheet"}
    docling_sheets = set(groups.values())
    items: list[StructuralItem] = []
    for sheet in workbook:
        if sheet.title not in docling_sheets:
            issues.append(_issue(SourceFormat.XLSX, "sheet_missing_in_docling", "Docling omitted workbook sheet", location=sheet.title, impact="sheet"))
            continue
        items.append(StructuralItem("heading", f"sheet:{sheet.title}",
                                    {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": "A1"},
                                    text=sheet.title, level=1))
        docling_tables = [table for table in raw.get("tables", [])
                          if groups.get((table.get("parent") or {}).get("$ref")) == sheet.title]
        for table in docling_tables:
            provenance = table.get("prov") or []
            box = provenance[0].get("bbox") if provenance else None
            if not box or box.get("coord_origin") != "TOPLEFT":
                issues.append(_issue(SourceFormat.XLSX, "table_range_unresolved", "Docling table has no usable sheet range", location=sheet.title, item_ref=table.get("self_ref")))
                continue
            first_row, first_col = int(box["t"]) + 1, int(box["l"]) + 1
            last_row, last_col = int(box["b"]), int(box["r"])
            if first_row < 1 or first_col < 1 or last_row < first_row or last_col < first_col or (last_row-first_row+1)*(last_col-first_col+1) > 100_000:
                issues.append(_issue(SourceFormat.XLSX, "table_range_invalid", "Docling table range is invalid or exceeds 100000 cells", location=sheet.title, item_ref=table.get("self_ref")))
                continue
            rows = _docling_cells(table)
            for parsed in table.get("data", {}).get("table_cells", []):
                r, c = parsed["start_row_offset_idx"], parsed["start_col_offset_idx"]
                if not (0 <= r < len(rows) and 0 <= c < len(rows[r])
                        and first_row + r <= last_row and first_col + c <= last_col):
                    issues.append(_issue(SourceFormat.XLSX, "table_range_invalid",
                        "Docling cell offset is outside its sheet range", item_ref=table.get("self_ref")))
                    continue
                cell = sheet.cell(first_row + r, first_col + c)
                rows[r][c] = _xlsx_cell(sheet, cached[sheet.title], cell, issues, parsed.get("text"))
            start = sheet.cell(first_row, first_col).coordinate
            end = sheet.cell(last_row, last_col).coordinate
            a1 = start if start == end else f"{start}:{end}"
            items.append(StructuralItem("table", f"sheet:{sheet.title}:{a1}",
                                        {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": a1}, cells=rows))
    workbook.close()
    cached.close()
    return items


def _xlsx_cell(sheet: Any, cached_sheet: Any, cell: Any, issues: list[ParseIssue],
               display_text: str | None = None) -> dict[str, Any]:
    value = cell.value
    cache = cached_sheet[cell.coordinate].value
    formula = value if cell.data_type == "f" else None
    if formula and cache is None:
        issues.append(_issue(SourceFormat.XLSX, "missing_cached_value", "Formula has no cached result; not evaluated", location=f"{sheet.title}!{cell.coordinate}"))
    merged = next((area for area in sheet.merged_cells.ranges if cell.coordinate in area), None)
    def json_value(item: Any) -> Any:
        return item.isoformat() if hasattr(item, "isoformat") else item
    from .xlsx_format import display_value
    literal = cache if formula else value
    display_text = display_value(literal, cell.number_format, fallback=display_text)
    result = {"value": json_value(cache if formula else value), "formula": formula,
            "cached_value": json_value(cache) if formula else None, "display_text": display_text,
            "locator": {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": cell.coordinate},
            "row_span": (merged.max_row - merged.min_row + 1) if merged and cell.row == merged.min_row and cell.column == merged.min_col else 1,
            "col_span": (merged.max_col - merged.min_col + 1) if merged and cell.row == merged.min_row and cell.column == merged.min_col else 1}
    return result


class DocumentParser:
    def __init__(self, *, profile: str = "C_tesseract", remote: Any = None, bbox_tolerance: float = 0):
        import math

        from .docling_profiles import validate_profile
        validate_profile(profile, remote)
        if not math.isfinite(bbox_tolerance) or not 0 <= bbox_tolerance <= 5:
            raise ValueError("bbox tolerance must be between 0 and 5 PDF points")
        self.profile = profile
        self.remote = remote
        self.bbox_tolerance = bbox_tolerance

    def parse(self, source: VerifiedSource, source_format: SourceFormat) -> StructuralParseResult:
        data = source.path.read_bytes()
        if len(data) != source.byte_size or sha256(data).hexdigest() != source.content_sha256:
            raise ValueError("verified source bytes changed before parsing")
        verify_format(data, source_format)
        if source_format in (SourceFormat.PNG, SourceFormat.JPEG):
            from .image_geometry import prepare_image
            prepared, metadata = prepare_image(data)
            with TemporaryDirectory(prefix="docgrain-image-") as directory:
                path = Path(directory) / "input.png"
                path.write_bytes(prepared)
                result = _docling(VerifiedSource(path, sha256(prepared).hexdigest(), len(prepared)), source_format,
                                  image_metadata=metadata, profile=self.profile, remote=self.remote)
            # Original binary is authoritative; prepared PNG is only OCR input.
            if result.status != "failed":
                picture = next(i for i in result.items if i.anchor == "original-image")
                picture.asset_bytes = data
        elif source_format is SourceFormat.PDF:
            from .image_budget import prepare_pdf, restore_pdf_geometry
            with TemporaryDirectory(prefix="docgrain-pdf-") as directory:
                path = Path(directory) / "input.pdf"
                geometry = prepare_pdf(source.path, path)
                parse_source = source
                if geometry:
                    prepared = path.read_bytes()
                    parse_source = VerifiedSource(path, sha256(prepared).hexdigest(), len(prepared))
                result = _docling(parse_source, source_format, profile=self.profile, remote=self.remote)
                if geometry:
                    restore_pdf_geometry(result, geometry)
                    for number, transform in geometry.items():
                        result.issues.append(_issue(source_format, "image_downscaled",
                            f"Sayfa küçültüldü: özgün boyut {transform['original_size']}; kullanılan boyut {transform['used_size']}",
                            location=f"page:{number}", impact="page"))
                    if result.status != "failed":
                        result.status = "partial"
        else:
            result = _txt(source) if source_format is SourceFormat.TXT else _docling(
                source, source_format, profile=self.profile, remote=self.remote)
        if source_format is SourceFormat.TXT:
            result.processing_options = {"encoding": "utf-8-sig", "paragraph_strategy": "exact-spans-v1"}
        if self.bbox_tolerance:
            result.processing_options["bbox_tolerance_points"] = self.bbox_tolerance
        from .docling_profiles import identity
        result.reading_profile = identity(self.profile, result.processing_options,
                                          remote=self.remote)
        return result
