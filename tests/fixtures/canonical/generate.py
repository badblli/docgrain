"""Regenerate synthetic M1 fixtures; these are not parser outputs or customer data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, canonical_json_bytes, deterministic_item_id

HERE = Path(__file__).resolve().parent
STAMP = "2026-09-28T10:00:00+00:00"


def annotation(evidence_id: str, *, status: str = "unreviewed") -> dict:
    return {
        "provenance": {
            "method": "parser", "derivation": "direct", "producer_id": "producer-synthetic",
            "evidence_ids": [evidence_id], "confidence": None,
        },
        "review_status": status,
    }


def base(document_id: str, source_id: str, revision_id: str) -> dict:
    return {
        "schema_version": "0.1.0", "identity_policy_version": "0.1.0",
        "document_id": document_id, "workspace_id": "workspace-synthetic",
        "source_version": {
            "id": source_id, "document_id": document_id, "workspace_id": "workspace-synthetic",
            "content_sha256": "a" * 64, "storage_uri": f"fixture://{document_id}/source",
            "storage_version": "fixture-v1", "byte_size": 100, "mime_type": "application/pdf",
            "filename": "example.pdf", "recorded_at": STAMP,
        },
        "knowledge_revision": {
            "id": revision_id, "document_id": document_id, "workspace_id": "workspace-synthetic",
            "source_version_id": source_id, "parent_revision_id": None, "created_at": STAMP,
            "producers": [{"id": "producer-synthetic", "name": "synthetic-fixture", "version": "1"}],
        },
        "root_node_id": deterministic_item_id(document_id, "document", "root"),
        "structure": [], "entities": [], "relations": [], "records": [], "evidence": [],
        "artifacts": [], "domain_schemas": [], "metadata": {"fixture": True},
    }


def generic_pdf() -> dict:
    doc = "document-generic-pdf"
    result = base(doc, "source-pdf", "revision-pdf")
    def ident(kind: str, key: str) -> str:
        return deterministic_item_id(doc, kind, key)
    result["structure"] = [
        {"kind": "document", "id": ident("document", "root"), "identity_key": "root",
         "title": "Field report", "annotation": annotation("evidence-page-1"),
         "children": [ident("section", "summary"), ident("table", "measurements")]},
        {"kind": "section", "id": ident("section", "summary"), "identity_key": "summary",
         "heading": "Summary", "level": 1, "annotation": annotation("evidence-page-1"),
         "children": [ident("text_block", "summary-paragraph")]},
        {"kind": "text_block", "id": ident("text_block", "summary-paragraph"),
         "identity_key": "summary-paragraph", "text": "İzmir site recorded 12 samples.",
         "annotation": annotation("evidence-paragraph")},
        {"kind": "table", "id": ident("table", "measurements"),
         "identity_key": "measurements", "annotation": annotation("evidence-table"),
         "rows": [[{"value": "Site", "annotation": annotation("evidence-cell-a1")},
                   {"value": "Samples", "annotation": annotation("evidence-cell-b1")}],
                  [{"value": "İzmir", "annotation": annotation("evidence-cell-a2")},
                   {"value": 12, "annotation": annotation("evidence-cell-b2")}]]},
    ]
    result["entities"] = [
        {"id": ident("entity", "site-izmir"), "identity_key": "site-izmir",
         "type": "site", "label": "İzmir", "annotation": annotation("evidence-paragraph"),
         "field_annotations": {"label": annotation("evidence-paragraph")}},
        {"id": ident("entity", "report"), "identity_key": "report",
         "type": "report", "label": "Field report", "annotation": annotation("evidence-page-1")},
    ]
    result["relations"] = [
        {"id": ident("relation", "report-site"), "identity_key": "report-site",
         "type": "mentions", "from_entity_id": ident("entity", "report"),
         "to_entity_id": ident("entity", "site-izmir"),
         "annotation": annotation("evidence-paragraph")},
    ]
    result["evidence"] = [
        {"id": evidence_id, "source_version_id": "source-pdf",
         "locator": {"kind": "pdf_page", "page_number": 1, "bbox": box}}
        for evidence_id, box in [
            ("evidence-page-1", None),
            ("evidence-paragraph", {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.1}),
            ("evidence-table", {"x": 0.1, "y": 0.4, "width": 0.8, "height": 0.3}),
            ("evidence-cell-a1", {"x": 0.1, "y": 0.4, "width": 0.2, "height": 0.1}),
            ("evidence-cell-b1", {"x": 0.3, "y": 0.4, "width": 0.2, "height": 0.1}),
            ("evidence-cell-a2", {"x": 0.1, "y": 0.5, "width": 0.2, "height": 0.1}),
            ("evidence-cell-b2", {"x": 0.3, "y": 0.5, "width": 0.2, "height": 0.1}),
        ]
    ]
    return result


def domain_example(schema_document: dict) -> dict:
    doc = "document-domain-example"
    result = base(doc, "source-sheet", "revision-sheet")
    result["source_version"].update({"mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                     "filename": "example.xlsx"})
    def ident(kind: str, key: str) -> str:
        return deterministic_item_id(doc, kind, key)
    result["structure"] = [
        {"kind": "document", "id": ident("document", "root"), "identity_key": "root",
         "annotation": annotation("evidence-sheet"), "children": [ident("table", "sheet1-a1-b2")]},
        {"kind": "table", "id": ident("table", "sheet1-a1-b2"),
         "identity_key": "sheet1-a1-b2", "annotation": annotation("evidence-sheet"),
         "rows": [[{"value": "Site"}, {"value": "Count"}],
                  [{"value": "İzmir", "annotation": annotation("evidence-site")},
                   {"value": 12, "annotation": annotation("evidence-count")}]]},
    ]
    result["evidence"] = [
        {"id": key, "source_version_id": "source-sheet",
         "locator": {"kind": "spreadsheet_range", "sheet": "Sheet1", "a1_range": a1}}
        for key, a1 in [("evidence-sheet", "A1:B2"), ("evidence-site", "A2"),
                        ("evidence-count", "B2")]
    ]
    result["domain_schemas"] = [{
        "id": "site-count", "version": "1", "content_sha256": hashlib.sha256(
            canonical_json_bytes(schema_document)).hexdigest(),
    }]
    result["records"] = [{
        "id": ident("record", "sheet1-row2"), "identity_key": "sheet1-row2",
        "schema_id": "site-count", "values": {"site": "İzmir", "count": 12},
        "annotation": annotation("evidence-sheet", status="proposed"),
        "field_annotations": {"site": annotation("evidence-site"),
                              "count": annotation("evidence-count")},
        "validation": {"status": "not_validated"},
    }]
    return result


def main() -> None:
    schema_document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["site", "count"],
        "properties": {"site": {"type": "string"}, "count": {"type": "integer", "minimum": 0}},
    }
    fixtures = {
        "generic-pdf.json": generic_pdf(),
        "domain-example.json": domain_example(schema_document),
        "domain-example.schema.json": schema_document,
    }
    for filename, value in fixtures.items():
        if filename != "domain-example.schema.json":
            value = CanonicalKnowledgeSnapshot.model_validate(value).model_dump(mode="json")
        (HERE / filename).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                                     encoding="utf-8")


if __name__ == "__main__":
    main()
