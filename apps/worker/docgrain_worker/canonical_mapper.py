"""StructuralParseResult to M1 canonical contract; no semantic enrichment."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pymupdf
from docgrain_domain.canonical import (
    Annotation,
    ArtifactRef,
    AssetNode,
    CanonicalKnowledgeSnapshot,
    ChartNode,
    DocumentNode,
    DocxBlockLocator,
    Evidence,
    ImageRegionLocator,
    KnowledgeRevision,
    ListNode,
    PdfPageLocator,
    Producer,
    Provenance,
    SectionNode,
    SourceVersion,
    SpreadsheetRangeLocator,
    TableCell,
    TableNode,
    TextBlock,
    TextSpanLocator,
    deterministic_item_id,
)
from docgrain_domain.canonical.lifecycle import ProcessingSpec

from .pdf_geometry import normalized_pdf_box
from .structural import ParseIssue, StructuralParseResult


class CanonicalMapper:
    def map(self, result: StructuralParseResult, source: SourceVersion, *,
            revision_id: str, created_at: datetime, pdf_path: Path | None = None,
            processing: ProcessingSpec | None = None,
            parent_revision_id: str | None = None) -> CanonicalKnowledgeSnapshot:
        if result.status == "failed":
            raise ValueError("failed structural parse cannot produce a canonical revision")
        document_id = source.document_id
        policy = processing.identity_policy_version if processing else "0.1.0"
        def item_id(document: str, kind: str, key: str) -> str:
            return deterministic_item_id(document, kind, key, policy_version=policy)

        occurrences: dict[tuple[str, str], int] = {}
        producer_id = "producer-structural-parser"
        root_id = item_id(document_id, "document", "root")
        root = DocumentNode(id=root_id, identity_key="root", title=source.filename,
                            annotation=_annotation(producer_id, []))
        structure: list[Any] = [root]
        evidence: list[Evidence] = []
        artifacts: list[ArtifactRef] = []
        if result.source_format.value == "pdf":
            for area in result.expected_areas:
                if area.startswith("page:"):
                    page_number = int(area.split(":", 1)[1])
                    evidence_id = f"evidence_{sha256(f'{source.id}:page:{page_number}'.encode()).hexdigest()[:32]}"
                    evidence.append(Evidence(id=evidence_id, source_version_id=source.id,
                                             locator=PdfPageLocator(page_number=page_number)))
                    root.annotation.provenance.evidence_ids.append(evidence_id)
        issues = [asdict(issue) for issue in result.issues]
        section_stack: list[SectionNode] = []
        previous_list: ListNode | None = None
        previous_part = None
        ocr_engine = result.processing_options.get("ocr_profile", {}).get("engine", "easyocr")
        native_profile = result.processing_options.get("adapter_version") == "n2-1"
        native_office = native_profile and result.source_format.value in {"docx", "xlsx"}
        native_pdf = native_profile and result.source_format.value == "pdf"
        pdf = pymupdf.open(pdf_path) if pdf_path is not None and result.source_format.value == "pdf" else None
        try:
            for item in result.items:
                part = (item.locator or {}).get("part")
                if part and part != previous_part:
                    section_stack.clear()
                    previous_list = None
                    previous_part = part
                if item.kind == "picture" and (not item.asset_bytes or not item.asset_path):
                    continue
                tolerance = result.processing_options.get("bbox_tolerance_points", 0)
                locator = _locator(item.locator, item.page_size, pdf, tolerance_points=tolerance)
                if item.locator and locator is None:
                    issues.append(asdict(ParseIssue("locator_unresolved", "canonical_mapping", result.source_format,
                                                    str(item.locator.get("page_number") or item.locator.get("sheet")),
                                                    item.anchor, "Source geometry/path could not be mapped", "item")))
                if isinstance(locator, PdfPageLocator) and locator.bbox is None:
                    issues.append(asdict(ParseIssue("bbox_unresolved", "canonical_mapping", result.source_format,
                                                    f"page:{locator.page_number}", item.anchor,
                                                    "PDF bbox is missing or outside the verified page frame", "item")))
                evidence_id = None
                if locator is not None:
                    key = f"{source.id}:{item.anchor}:{locator.model_dump_json()}"
                    evidence_id = f"evidence_{sha256(key.encode()).hexdigest()[:32]}"
                    evidence.append(Evidence(id=evidence_id, source_version_id=source.id, locator=locator))
                anchor = (_stable_anchor(locator) if processing else _identity_anchor(item, locator, section_stack))
                if anchor is not None and processing:
                    pair = (item.kind, anchor)
                    ordinal = occurrences.get(pair, 0)
                    occurrences[pair] = ordinal + 1
                    anchor = f"{anchor}:occurrence:{ordinal}"
                if anchor is None:
                    issues.append(asdict(ParseIssue("identity_unresolved", "canonical_mapping", result.source_format,
                                                    None, item.anchor, "No stable source anchor", "item")))
                    continue
                annotation = _extraction_annotation(item.text_origin, item.ocr_confidence, [evidence_id] if evidence_id else [], engine=ocr_engine)
                if native_office:
                    annotation.provenance.producer_id = "producer-native-ooxml"
                    annotation.provenance.method = "source"
                if native_pdf and (item.locator or {}).get("kind") == "pdf_native":
                    annotation.provenance.producer_id = "producer-native-pdf"
                    annotation.provenance.method = "source"
                if item.kind == "heading":
                    key = f"heading:{anchor}"
                    node = SectionNode(id=item_id(document_id, "section", key), identity_key=key,
                                       heading=item.text, level=item.level, annotation=annotation)
                    while section_stack and section_stack[-1].level >= node.level:
                        section_stack.pop()
                    parent = section_stack[-1] if section_stack else root
                    parent.children.append(node.id)
                    structure.append(node)
                    section_stack.append(node)
                    previous_list = None
                elif item.kind == "list_item":
                    parent = section_stack[-1] if section_stack else root
                    if previous_list is None:
                        list_key = f"list:{anchor}"
                        previous_list = ListNode(id=item_id(document_id, "list", list_key),
                                                 identity_key=list_key, annotation=annotation)
                        structure.append(previous_list)
                        parent.children.append(previous_list.id)
                    key = f"list-text:{anchor}"
                    node = TextBlock(id=item_id(document_id, "text_block", key),
                                     identity_key=key, text=item.text, annotation=annotation)
                    previous_list.children.append(node.id)
                    structure.append(node)
                else:
                    previous_list = None
                    parent = section_stack[-1] if section_stack else root
                    if item.kind == "picture":
                        digest = sha256(item.asset_bytes).hexdigest()
                        artifact_id = "artifact_" + digest[:32]
                        if not any(a.id == artifact_id for a in artifacts):
                            artifacts.append(ArtifactRef(id=artifact_id, role="source-image",
                                                         storage_uri=item.asset_path, content_sha256=digest,
                                                         byte_size=len(item.asset_bytes),
                                                         mime_type=item.asset_mime or "application/octet-stream"))
                        key = f"asset:{anchor}"
                        node = AssetNode(id=item_id(document_id, "asset", key),
                                         identity_key=key, artifact_id=artifact_id, annotation=annotation)
                    elif item.kind == "table":
                        key = f"table:{anchor}"
                        rows = []
                        for row in item.cells:
                            mapped_row = []
                            for cell in row:
                                cell_evidence_id = None
                                cell_locator = _locator(cell.get("locator"), item.page_size, pdf, tolerance_points=tolerance)
                                if cell_locator is not None:
                                    cell_key = f"{source.id}:{cell_locator.model_dump_json()}"
                                    cell_evidence_id = f"evidence_{sha256(cell_key.encode()).hexdigest()[:32]}"
                                    if not any(e.id == cell_evidence_id for e in evidence):
                                        evidence.append(Evidence(id=cell_evidence_id, source_version_id=source.id,
                                                                 locator=cell_locator))
                                mapped_row.append(TableCell(
                                    value=cell.get("value"), formula=cell.get("formula"),
                                    cached_value=cell.get("cached_value"), display_text=cell.get("display_text"),
                                    row_span=cell.get("row_span", 1), col_span=cell.get("col_span", 1),
                                    source_attributes=cell.get("source_attributes"),
                                    annotation=_extraction_annotation(cell.get("text_origin", "native"), cell.get("ocr_confidence"),
                                                                      [cell_evidence_id], engine=ocr_engine) if cell_evidence_id else None,
                                ))
                                if native_office and mapped_row[-1].annotation:
                                    mapped_row[-1].annotation.provenance.producer_id = "producer-native-ooxml"
                                    mapped_row[-1].annotation.provenance.method = "source"
                                if native_pdf and mapped_row[-1].annotation and (cell.get("locator") or {}).get("kind") == "pdf_native":
                                    mapped_row[-1].annotation.provenance.producer_id = "producer-native-pdf"
                                    mapped_row[-1].annotation.provenance.method = "source"
                            rows.append(mapped_row)
                        node = TableNode(id=item_id(document_id, "table", key),
                                         identity_key=key, rows=rows, annotation=annotation)
                    elif item.kind == "chart":
                        key = f"chart:{anchor}"
                        node = ChartNode(id=item_id(document_id, "chart", key),
                                         identity_key=key, description=None, annotation=annotation, source_data=item.source_data)
                        for field_name, field_raw in item.field_locators.items():
                            field_locator = _locator(field_raw, item.page_size, pdf)
                            if field_locator is not None:
                                field_id = "evidence_" + sha256(f"{source.id}:{field_locator.model_dump_json()}".encode()).hexdigest()[:32]
                                if not any(e.id == field_id for e in evidence):
                                    evidence.append(Evidence(id=field_id, source_version_id=source.id, locator=field_locator))
                                field_annotation = _annotation("producer-native-ooxml", [field_id])
                                field_annotation.provenance.method = "source"
                                node.field_annotations[field_name] = field_annotation
                    else:
                        key = f"text:{anchor}"
                        node = TextBlock(id=item_id(document_id, "text_block", key),
                                         identity_key=key, text=item.text, annotation=annotation)
                    parent.children.append(node.id)
                    structure.append(node)
        finally:
            if pdf is not None:
                pdf.close()
        coverage = result.coverage
        if issues:
            coverage["status"] = "partial"
        producers = [Producer(id=producer_id, name=result.parser, version=result.parser_version,
                              configuration_digest=processing.digest if processing else None)]
        if result.processing_options.get("ocr_profile"):
            producers.append(Producer(id=f"producer-{ocr_engine}",
                                      name="Docling + EasyOCR (literal OCR / mixed native+OCR)" if ocr_engine == "easyocr" else "Docling + Tesseract (literal OCR / mixed native+OCR)",
                                      version="1.7.2" if ocr_engine == "easyocr" else result.processing_options["ocr_profile"].get("version", "system"),
                                      configuration_digest=processing.digest if processing else None))
        if native_office:
            producers.append(Producer(id="producer-native-ooxml", name="Native OOXML (literal parts/cells/chart references)",
                version="n2-1", configuration_digest=processing.digest if processing else None))
        if native_pdf:
            import importlib.metadata
            producers.append(Producer(id="producer-native-pdf", name="PyMuPDF native words + ruled cell geometry",
                version=importlib.metadata.version("pymupdf"), configuration_digest=processing.digest if processing else None))
        revision = KnowledgeRevision(id=revision_id, document_id=document_id, workspace_id=source.workspace_id,
                                     source_version_id=source.id, created_at=created_at,
                                     parent_revision_id=parent_revision_id, processing=processing,
                                     producers=tuple(producers),
                                     coverage=coverage["status"])
        return CanonicalKnowledgeSnapshot(
            schema_version=processing.schema_version if processing else "0.2.0", identity_policy_version=policy,
            document_id=document_id, workspace_id=source.workspace_id,
            source_version=source, knowledge_revision=revision, root_node_id=root_id,
            structure=structure, evidence=evidence, artifacts=artifacts,
            metadata={"structural_parse": {"coverage": coverage, "issues": issues,
                                           "source_format": result.source_format.value,
                                           "parser": result.parser, "parser_version": result.parser_version},
                      **({"source_extraction": result.source_metadata} if result.processing_options.get("adapter_version") in {"n1-1", "n2-1"} else {}),
                      **({"docling_confidence": result.source_metadata["docling_confidence"]}
                         if "docling_confidence" in result.source_metadata else {})},
        )


def _annotation(producer_id: str, evidence_ids: list[str]) -> Annotation:
    return Annotation(provenance=Provenance(method="parser", derivation="direct", producer_id=producer_id,
                                            evidence_ids=evidence_ids))


def _extraction_annotation(origin: str, confidence: float | None, evidence_ids: list[str], *, engine: str = "easyocr") -> Annotation:
    annotation = _annotation(f"producer-{engine}" if origin in {"ocr", "mixed"} else "producer-structural-parser", evidence_ids)
    if origin in {"ocr", "mixed"}:
        annotation.provenance.confidence = confidence
        annotation.provenance.confidence_method = f"{engine}-recognition-min:{origin}"
    return annotation


def _locator(raw: dict[str, Any] | None, size: tuple[float, float] | None,
             pdf: pymupdf.Document | None, *, tolerance_points: float = 0) -> Any | None:
    if raw is None:
        return None
    if raw["kind"] == "pdf_raw":
        number = raw["page_number"]
        if pdf is None or number < 1 or number > len(pdf):
            return None
        box = normalized_pdf_box(raw.get("bbox"), size or (0, 0), pdf[number - 1], frame=raw.get("frame"),
                                 tolerance_points=tolerance_points)
        return PdfPageLocator(page_number=number, bbox=box)
    if raw["kind"] == "pdf_native":
        if pdf is None or not 1 <= raw["page_number"] <= len(pdf):
            return None
        page = pdf[raw["page_number"]-1]
        box = normalized_pdf_box({"l": raw["rect"][0], "t": raw["rect"][1], "r": raw["rect"][2], "b": raw["rect"][3],
                                  "coord_origin": "TOPLEFT"}, (page.cropbox.width,page.cropbox.height), page)
        return PdfPageLocator(page_number=raw["page_number"], bbox=box)
    if raw["kind"] == "docx_block":
        return DocxBlockLocator(part=raw["part"], path=raw["path"])
    if raw["kind"] == "text_span":
        return TextSpanLocator(start=raw["start"], end=raw["end"])
    if raw["kind"] == "spreadsheet_range":
        return SpreadsheetRangeLocator(sheet=raw["sheet"], a1_range=raw["a1_range"])
    if raw["kind"] == "image_region":
        return ImageRegionLocator.model_validate(raw)
    return None


def _identity_anchor(item: Any, locator: Any | None, sections: list[SectionNode]) -> str | None:
    if locator is None:
        return None
    context = "/".join(section.identity_key for section in sections)
    if isinstance(locator, PdfPageLocator):
        if locator.bbox is None:
            return (f"pdf:{locator.page_number}:page-only:{context}:"
                    f"{sha256(item.text.encode()).hexdigest()[:16]}:{item.anchor}") if item.text else None
        box = locator.bbox
        geometry = ":".join(f"{v:.4f}" for v in (box.x, box.y, box.width, box.height))
        return f"pdf:{locator.page_number}:{geometry}:{context}:{sha256(item.text.encode()).hexdigest()[:8]}"
    if isinstance(locator, DocxBlockLocator):
        return f"docx:{locator.part}:{locator.path}:{context}"
    if isinstance(locator, TextSpanLocator):
        return f"txt:{locator.start}:{locator.end}:{context}"
    if isinstance(locator, ImageRegionLocator):
        raise TypeError("image locations require processing identity policy 0.2.0")
    return f"xlsx:{locator.sheet}:{locator.a1_range}:{context}"


def _stable_anchor(locator: Any | None) -> str | None:
    """Identity policy 0.2.0: source location, independent of text/ancestors/config."""
    if locator is None:
        return None
    if isinstance(locator, PdfPageLocator):
        if locator.bbox is None:
            return f"pdf:{locator.page_number}:page-only"
        box = locator.bbox
        geometry = ":".join(f"{v:.4f}" for v in (box.x, box.y, box.width, box.height))
        return f"pdf:{locator.page_number}:{geometry}"
    if isinstance(locator, DocxBlockLocator):
        return f"docx:{locator.part}:{locator.path}"
    if isinstance(locator, TextSpanLocator):
        return f"txt:{locator.start}"
    if isinstance(locator, ImageRegionLocator):
        box = locator.bbox
        return "image:" + ":".join(f"{v:.6f}" for v in (box.x, box.y, box.width, box.height))
    return f"xlsx:{locator.sheet}:{locator.a1_range}"
