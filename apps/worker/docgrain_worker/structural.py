"""Format-neutral structural extraction; Docling never crosses this boundary."""

from __future__ import annotations

import base64
import importlib.metadata
import re
from tempfile import TemporaryDirectory
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from zipfile import ZipFile

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


def _docling(source: VerifiedSource, fmt: SourceFormat, *, ocr_enabled: bool = False,
             image_metadata: dict | None = None) -> StructuralParseResult:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption

    is_image = fmt in (SourceFormat.PNG, SourceFormat.JPEG)
    input_format = InputFormat.IMAGE if is_image else InputFormat(fmt.value)
    pipeline = PdfPipelineOptions(do_ocr=ocr_enabled, generate_picture_images=True)
    if ocr_enabled:
        from .ocr import options as ocr_options, verified_profile
        pipeline.ocr_options = ocr_options()
        pipeline.accelerator_options = AcceleratorOptions(device="cpu", num_threads=2)
        pipeline.generate_parsed_pages = True

    options = {InputFormat.PDF: PdfFormatOption(
        pipeline_options=pipeline
    )} if fmt is SourceFormat.PDF else {}
    if is_image:
        options[InputFormat.IMAGE] = ImageFormatOption(pipeline_options=pipeline)
    converter = DocumentConverter(allowed_formats=[input_format], format_options=options)
    processing_options = {
        "pipeline": converter.format_to_options[input_format].pipeline_options.model_dump(mode="json"),
        "adapter_version": "m1b-1", "formula_evaluation": False,
    }
    if ocr_enabled or is_image:
        processing_options["adapter_version"] = "n1-1"
        processing_options["canonical_schema_version"] = "0.5.0"
        if ocr_enabled:
            processing_options["ocr_profile"] = verified_profile()
            # Installation path is operational, not part of semantic configuration identity.
            processing_options["pipeline"]["ocr_options"]["model_storage_directory"] = "pinned-checkpoints"
        if image_metadata:
            processing_options["image_preparation"] = image_metadata
    converted = converter.convert(source.path, raises_on_error=False)
    version = importlib.metadata.version("docling")
    if converted.document is None:
        return StructuralParseResult(fmt, "docling", version, "failed", [], [], [],
                                     [_issue(fmt, "conversion_failed", str(converted.errors)[:1000], impact="document")])
    raw = converted.document.export_to_dict()
    pages = raw.get("pages", {})
    issues: list[ParseIssue] = []
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
    else:
        for ref in _reading_refs(raw.get("body", {}), raw, lookup):
            item = lookup[ref]
            label = item.get("label", "")
            kind = {"section_header": "heading", "title": "heading", "list_item": "list_item",
                    "table": "table", "picture": "picture"}.get(label, "paragraph")
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
    if fmt is SourceFormat.DOCX:
        _docx_paths(source, items, issues)
    ocr_cells = []
    if ocr_enabled:
        ocr_cells = _tag_ocr(converted, raw, items, fmt, issues, image_metadata)
    if fmt is SourceFormat.PDF:
        _pdf_missing_tables(source, items, issues, pages)
        for area in expected:
            if area not in processed:
                issues.append(_issue(fmt, "missing_page", "Docling page geometry is unavailable", location=area, impact="page"))
            elif not any(i.locator and i.locator.get("page_number") == int(area.split(":")[1]) and i.kind != "picture" for i in items):
                reason = ("No structural text/table on page; OCR/visual review required" if ocr_enabled
                          else "No structural text/table on page; OCR is outside M1b")
                issues.append(_issue(fmt, "low_text_page", reason, location=area, impact="page"))
    if is_image:
        # Always preserve the exact original binary independently of Docling picture detection.
        original = source.path.read_bytes()
        locator = {"kind": "image_region", **{k: image_metadata[k] for k in ("width_px", "height_px", "exif_orientation")},
                   "bbox": {"x": 0, "y": 0, "width": 1, "height": 1}}
        items.append(StructuralItem("picture", "original-image", locator,
            asset_bytes=original, asset_mime="image/png" if fmt is SourceFormat.PNG else "image/jpeg"))
        if not any(i.kind in {"paragraph", "heading", "list_item", "table"} for i in items):
            issues.append(_issue(fmt, "no_ocr_text", "No OCR text found; visual content is not interpreted", location="image"))
    if str(converted.status).lower().endswith("partial_success"):
        issues.append(_issue(fmt, "docling_partial", str(converted.errors)[:1000], impact="document"))
    status = "partial" if issues else "complete"
    result = StructuralParseResult(fmt, "docling", version, status, items, expected, processed, issues,
                                   {"docling_status": str(converted.status), "pages": pages},
                                   processing_options=processing_options)
    if ocr_enabled or is_image:
        import json
        result.source_metadata.update({"ocr_cells": ocr_cells, "image_preparation": image_metadata})
        result.legacy_markdown = converted.document.export_to_markdown().encode()
        result.legacy_json = json.dumps(raw, ensure_ascii=False).encode()
    return result


def _tag_ocr(converted, raw: dict, items: list[StructuralItem], fmt: SourceFormat,
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
        if any(c.confidence < 0.8 for c in ocr):
            issues.append(_issue(fmt, "ocr_low_confidence", "OCR recognition confidence below 0.8; literal retained", location=area, impact="page"))
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


def _pdf_missing_tables(source: VerifiedSource, items: list[StructuralItem],
                        issues: list[ParseIssue], pages: dict[str, Any]) -> None:
    """Narrow deterministic fallback when Docling omits a ruled PDF table."""
    import pymupdf

    document = pymupdf.open(source.path)
    try:
        for page_number, page in enumerate(document, start=1):
            if page.rotation or any(item.kind == "table" and item.locator and
                                    item.locator.get("page_number") == page_number for item in items):
                continue
            size = pages.get(str(page_number), {}).get("size", {})
            width, height = float(size.get("width", 0)), float(size.get("height", 0))
            if width <= 0 or height <= 0:
                continue
            for found in page.find_tables().tables:
                x0, y0, x1, y1 = found.bbox
                if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                    issues.append(_issue(SourceFormat.PDF, "table_fallback_geometry", "PyMuPDF table cannot be aligned to Docling page", location=f"page:{page_number}"))
                    continue
                rows = [[{"value": value or ""} for value in row] for row in found.extract()]
                if not rows:
                    continue
                indices = []
                for index, item in enumerate(items):
                    raw = (item.locator or {}).get("bbox") or {}
                    if (item.locator or {}).get("page_number") != page_number or not raw:
                        continue
                    cx = (raw["l"] + raw["r"]) / 2
                    cy = height - (raw["t"] + raw["b"]) / 2 if raw.get("coord_origin") == "BOTTOMLEFT" else (raw["t"] + raw["b"]) / 2
                    if x0 <= cx <= x1 and y0 <= cy <= y1 and item.kind == "paragraph":
                        indices.append(index)
                insert_at = min(indices) if indices else len(items)
                for index in reversed(indices):
                    items.pop(index)
                locator = {"kind": "pdf_raw", "page_number": page_number,
                           "bbox": {"l": x0, "t": height - y0, "r": x1, "b": height - y1,
                                    "coord_origin": "BOTTOMLEFT"}}
                items.insert(insert_at, StructuralItem("table", f"pdf-table:{page_number}:{x0}:{y0}:{x1}:{y1}",
                                                       locator, cells=rows, page_size=(width, height)))
                issues.append(_issue(SourceFormat.PDF, "docling_missed_table",
                                     "Docling omitted a ruled table; PyMuPDF recovered its cells",
                                     location=f"page:{page_number}", impact="table"))
    finally:
        document.close()


def _docx_paths(source: VerifiedSource, items: list[StructuralItem], issues: list[ParseIssue]) -> None:
    """Narrow OOXML locator pass; Docling still supplies all structural content."""
    from xml.etree import ElementTree as ET
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(source.path) as package:
        root = ET.fromstring(package.read("word/document.xml"))
    body = root.find("w:body", ns)
    if body is None:
        issues.append(_issue(SourceFormat.DOCX, "missing_body", "OOXML document body missing", impact="document"))
        return
    blocks: list[tuple[str, str, bool]] = []
    for n, block in enumerate(body):
        tag = block.tag.rsplit("}", 1)[-1]
        if tag not in {"p", "tbl"}:
            continue
        text = "".join(t.text or "" for t in block.findall(".//w:t", ns))
        path = f"/document/body/{tag}[{n + 1}]"
        paragraph_id = block.attrib.get("{http://schemas.microsoft.com/office/word/2010/wordml}paraId")
        if paragraph_id:
            path += f"#paraId={paragraph_id}"
        blocks.append((text, path, block.find(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline") is not None))
    cursor = 0
    for item in items:
        if item.kind == "picture":
            found = next((i for i in range(cursor, len(blocks)) if blocks[i][2]), None)
            if found is None:
                issues.append(_issue(SourceFormat.DOCX, "picture_locator_unresolved", "Cannot align Docling picture with OOXML drawing", item_ref=item.anchor))
                item.locator = None
            else:
                item.locator = {"kind": "docx_block", "part": "word/document.xml", "path": blocks[found][1]}
                item.anchor = f"word/document.xml:{blocks[found][1]}"
                cursor = found + 1
            continue
        candidate = item.text if item.kind != "table" else "".join(str(c.get("value", "")) for row in item.cells for c in row)
        found = next((i for i in range(cursor, len(blocks)) if candidate and
                      (candidate == blocks[i][0] or candidate in blocks[i][0])), None)
        if found is None:
            issues.append(_issue(SourceFormat.DOCX, "locator_unresolved", "Cannot align Docling item with OOXML block", item_ref=item.anchor))
            item.locator = None
        else:
            item.locator = {"kind": "docx_block", "part": "word/document.xml", "path": blocks[found][1]}
            item.anchor = f"word/document.xml:{blocks[found][1]}"
            cursor = found + 1


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
        items.append(StructuralItem("heading", f"sheet:{sheet.title}",
                                    {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": "A1"},
                                    text=sheet.title, level=1))
        covered: set[str] = set()
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
            rows = []
            grid = table.get("data", {}).get("grid", [])
            for row_number in range(first_row, last_row + 1):
                row = []
                for column_number in range(first_col, last_col + 1):
                    cell = sheet.cell(row_number, column_number)
                    covered.add(cell.coordinate)
                    grid_row = row_number - first_row
                    grid_col = column_number - first_col
                    display = (grid[grid_row][grid_col].get("text")
                               if grid_row < len(grid) and grid_col < len(grid[grid_row]) else None)
                    row.append(_xlsx_cell(sheet, cached[sheet.title], cell, issues, display))
                rows.append(row)
            start = sheet.cell(first_row, first_col).coordinate
            end = sheet.cell(last_row, last_col).coordinate
            a1 = start if start == end else f"{start}:{end}"
            items.append(StructuralItem("table", f"sheet:{sheet.title}:{a1}",
                                        {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": a1}, cells=rows))
        # Docling can omit isolated formulas/cells. Preserve each as a small
        # source-fidelity fallback and mark the omission explicitly.
        for cell in list(sheet._cells.values()):
            if cell.value is None or cell.coordinate in covered:
                continue
            issues.append(_issue(SourceFormat.XLSX, "cell_missing_in_docling", "Source cell was absent from Docling table ranges", location=f"{sheet.title}!{cell.coordinate}"))
            items.append(StructuralItem("table", f"sheet:{sheet.title}:{cell.coordinate}",
                                        {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": cell.coordinate},
                                        cells=[[_xlsx_cell(sheet, cached[sheet.title], cell, issues)]]))
        for chart in sheet._charts:
            anchor = getattr(chart, "anchor", None)
            origin = getattr(anchor, "_from", None)
            if origin is None:
                issues.append(_issue(SourceFormat.XLSX, "chart_anchor_missing", "Chart has no source anchor", location=sheet.title))
                continue
            coordinate = sheet.cell(origin.row + 1, origin.col + 1).coordinate
            locator = {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": coordinate}
            items.append(StructuralItem("chart", f"chart:{sheet.title}:{coordinate}", locator))
            issues.append(_issue(SourceFormat.XLSX, "chart_not_interpreted", "Chart binary/data is not extracted", location=sheet.title))
        for image in sheet._images:
            anchor = getattr(image.anchor, "_from", None)
            if anchor is None:
                issues.append(_issue(SourceFormat.XLSX, "image_anchor_missing", "Image has no source anchor", location=sheet.title))
                continue
            coordinate = sheet.cell(anchor.row + 1, anchor.col + 1).coordinate
            locator = {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": coordinate}
            try:
                data = image._data()
            except (OSError, ValueError):
                issues.append(_issue(SourceFormat.XLSX, "image_not_extracted", "Image binary could not be read", location=sheet.title))
                continue
            items.append(StructuralItem("picture", f"image:{sheet.title}:{coordinate}", locator,
                                        asset_bytes=data, asset_mime=f"image/{image.format}"))
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
    return {"value": json_value(cache if formula else value), "formula": formula,
            "cached_value": json_value(cache) if formula else None, "display_text": display_text,
            "locator": {"kind": "spreadsheet_range", "sheet": sheet.title, "a1_range": cell.coordinate},
            "row_span": (merged.max_row - merged.min_row + 1) if merged and cell.row == merged.min_row and cell.column == merged.min_col else 1,
            "col_span": (merged.max_col - merged.min_col + 1) if merged and cell.row == merged.min_row and cell.column == merged.min_col else 1}


class DocumentParser:
    def __init__(self, *, ocr_enabled: bool = False):
        self.ocr_enabled = ocr_enabled

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
                                  ocr_enabled=self.ocr_enabled, image_metadata=metadata)
            # Original binary is authoritative; prepared PNG is only OCR input.
            if result.status != "failed":
                picture = next(i for i in result.items if i.anchor == "original-image")
                picture.asset_bytes = data
        else:
            result = _txt(source) if source_format is SourceFormat.TXT else _docling(
                source, source_format, ocr_enabled=self.ocr_enabled and source_format is SourceFormat.PDF)
        if source_format is SourceFormat.TXT:
            result.processing_options = {"encoding": "utf-8-sig", "paragraph_strategy": "exact-spans-v1"}
        return result
