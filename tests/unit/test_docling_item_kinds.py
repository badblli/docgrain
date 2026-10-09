"""WP107: Docling items are kept by collection (document_index tables, chart pictures, picture children)."""

import base64
import importlib.metadata
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pymupdf
import pytest
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import (
    processing_revision_id,
    source_revision_id,
)
from docgrain_domain.canonical.validation import validate_snapshot
from docgrain_domain.source_format import SourceFormat
from docgrain_worker import docling_profiles, structural
from docgrain_worker.canonical_mapper import CanonicalMapper
from docgrain_worker.canonical_writer import processing_spec
from docgrain_worker.structural import VerifiedSource, _docling, _item_kind


@pytest.mark.parametrize(("ref", "label", "kind"), [
    ("#/tables/0", "document_index", "table"),
    ("#/tables/1", "table", "table"),
    ("#/pictures/0", "chart", "picture"),
    ("#/pictures/1", "picture", "picture"),
    ("#/texts/0", "section_header", "heading"),
    ("#/texts/1", "title", "heading"),
    ("#/texts/2", "list_item", "list_item"),
    ("#/texts/3", "text", "paragraph"),
    ("#/texts/4", "caption", "paragraph"),
])
def test_item_kind_follows_docling_collection(ref, label, kind):
    assert _item_kind(ref, label) == kind


def _png() -> str:
    from PIL import Image
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (90, 40, 20)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _prov(l, t, r, b):
    return [{"page_no": 1, "bbox": {"l": l, "t": t, "r": r, "b": b, "coord_origin": "TOPLEFT"}}]


def _cell(row, col, text, top):
    return {"start_row_offset_idx": row, "start_col_offset_idx": col, "text": text,
            "bbox": {"l": 40 + col * 200, "t": top, "r": 220 + col * 200, "b": top + 12, "coord_origin": "TOPLEFT"}}


def test_price_list_chart_and_picture_text_reach_the_canonical_snapshot(monkeypatch, tmp_path):
    """Fake Docling output shaped like the designed wine menu: the list is a `document_index` table."""
    path = tmp_path / "menu.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=420, height=595)
        pdf.save(path)
    data = path.read_bytes()
    verified = VerifiedSource(path, sha256(data).hexdigest(), len(data))
    image = {"mimetype": "image/png", "uri": _png()}
    raw = {"pages": {"1": {"size": {"width": 420, "height": 595}}},
           "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"},
                                 {"$ref": "#/pictures/0"}, {"$ref": "#/pictures/1"}]},
           "texts": [{"self_ref": "#/texts/0", "label": "section_header", "text": "Example Drinks List",
                      "prov": _prov(40, 40, 300, 60)},
                     {"self_ref": "#/texts/1", "label": "text", "text": "Fresh every morning",
                      "parent": {"$ref": "#/pictures/0"}, "prov": _prov(60, 420, 250, 435)}],
           "tables": [{"self_ref": "#/tables/0", "label": "document_index", "prov": _prov(40, 80, 400, 140),
                       "data": {"num_rows": 2, "num_cols": 2, "table_cells": [
                           _cell(0, 0, "Lemon Soda 33 cl", 80), _cell(0, 1, "4 EUR", 80),
                           _cell(1, 0, "Orange Juice 25 cl", 110), _cell(1, 1, "5 EUR", 110)]}}],
           "pictures": [{"self_ref": "#/pictures/0", "label": "picture", "prov": _prov(40, 400, 400, 560),
                         "children": [{"$ref": "#/texts/1"}], "image": image},
                        {"self_ref": "#/pictures/1", "label": "chart", "prov": _prov(40, 160, 200, 300),
                         "image": image}]}
    converted = SimpleNamespace(status="SUCCESS", pages=[], document=SimpleNamespace(
        export_to_dict=lambda: raw, export_to_markdown=lambda: ""), confidence=None)
    converter = SimpleNamespace(convert=lambda *a, **kw: converted, format_to_options={
        "pdf": SimpleNamespace(pipeline_options=SimpleNamespace(model_dump=lambda **kw: {}))})
    monkeypatch.setattr(docling_profiles, "build_converter", lambda *a, **kw: (converter, "pdf"))
    monkeypatch.setattr(structural, "_bind_ocr_provenance", lambda *a: [])
    original_version = importlib.metadata.version
    monkeypatch.setattr(importlib.metadata, "version",
                        lambda name: "2.130.0" if name == "docling" else original_version(name))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="", stderr="tesseract 5.5\n"))

    result = _docling(verified, SourceFormat.PDF, profile="C_tesseract")

    assert [(i.kind, i.anchor) for i in result.items] == [
        ("heading", "#/texts/0"), ("table", "#/tables/0"), ("picture", "#/pictures/0"),
        ("paragraph", "#/texts/1"), ("picture", "#/pictures/1")]
    table = result.items[1]
    assert [[c["value"] for c in row] for row in table.cells] == [
        ["Lemon Soda 33 cl", "4 EUR"], ["Orange Juice 25 cl", "5 EUR"]]
    assert not [i for i in result.issues if i.code == "unextracted_picture"]
    assert result.processing_options["docling_item_kinds"] == "collection-v1"

    for item in result.items:
        if item.asset_bytes:
            item.asset_path = "fixture://image/" + sha256(item.asset_bytes).hexdigest()
    spec = processing_spec(result)
    source = SourceVersion(id=source_revision_id("w", "d", verified.content_sha256), document_id="d",
        workspace_id="w", content_sha256=verified.content_sha256, storage_uri="fixture://source",
        storage_version="1", byte_size=len(data), mime_type="application/pdf", filename=path.name,
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    snapshot = CanonicalMapper().map(result, source, revision_id=processing_revision_id(source.id, spec),
                                     created_at=source.recorded_at, pdf_path=path, processing=spec)
    validate_snapshot(snapshot)
    kinds = [node.kind for node in snapshot.structure]
    assert kinds.count("table") == 1 and kinds.count("asset") == 2
    rows = next(node.rows for node in snapshot.structure if node.kind == "table")
    assert [[cell.value for cell in row] for row in rows][1] == ["Orange Juice 25 cl", "5 EUR"]
    # Picture children keep their own bbox evidence on the page.
    text = next(node for node in snapshot.structure
                if node.kind == "text_block" and node.text == "Fresh every morning")
    evidence = {e.id: e for e in snapshot.evidence}
    locator = evidence[text.annotation.provenance.evidence_ids[0]].locator
    assert locator.page_number == 1 and locator.bbox is not None
    issues = snapshot.metadata["structural_parse"]["issues"]
    assert not [i for i in issues if i["code"] in {"bbox_unresolved", "identity_unresolved"}]


def test_processing_identity_changes_with_item_kind_policy(tmp_path):
    """Reprocessing after WP107 is a new revision, never a silent rewrite of an old one."""
    from docgrain_worker.docling_profiles import identity
    before = {"adapter_version": "docling-2"}
    after = {**before, "docling_item_kinds": "collection-v1"}
    assert identity("C_tesseract", before)["option_digest"] != identity("C_tesseract", after)["option_digest"]
