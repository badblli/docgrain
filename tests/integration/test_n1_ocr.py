"""Real local OCR over frozen pixels, scanned/mixed PDFs and EXIF-oriented JPEG."""

import importlib.util
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.ai_output import output_bundle
from docgrain_domain.canonical.lifecycle import (
    processing_revision_id,
    source_revision_id,
)
from docgrain_domain.source_format import MIME_TYPES, SourceFormat
from docgrain_worker.canonical_mapper import CanonicalMapper
from docgrain_worker.canonical_writer import processing_spec
from docgrain_worker.structural import DocumentParser, VerifiedSource

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("easyocr") is None, reason="pinned EasyOCR worker required"
)
GOLDEN = ["ODA SAYISI 127", "Room area 42 m2", "Türkçe: ç ş ğ ü ö İ ı"]


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    import pymupdf
    from PIL import Image

    root = tmp_path_factory.mktemp("n1-ocr")
    png = Path("tests/fixtures/structural/printed-tr-en.png")
    with Image.open(png) as image:
        exif = Image.Exif()
        exif[274] = 6
        image.transpose(Image.Transpose.ROTATE_90).save(
            root / "oriented.jpg", quality=98, exif=exif
        )
    for name in ("scan", "mixed", "overlap"):
        pdf = pymupdf.open()
        page = pdf.new_page(width=750, height=500)
        page.insert_image(pymupdf.Rect(0, 130, 750, 380), filename=str(png))
        if name == "mixed":
            page.insert_text((40, 40), "Native exact 987", fontsize=16)
        if name == "overlap":
            # Same physical region as the raster first line: PDF text must win, never duplicate.
            page.insert_text((30, 183), GOLDEN[0], fontsize=24)
        pdf.save(root / f"{name}.pdf")
        pdf.close()
    Image.new("RGB", (200, 100), "white").save(root / "blank.png")
    return {
        "png": png,
        "jpeg": root / "oriented.jpg",
        "blank": root / "blank.png",
        **{name: root / f"{name}.pdf" for name in ("scan", "mixed", "overlap")},
    }


@pytest.mark.parametrize(
    "name,fmt",
    [
        ("png", SourceFormat.PNG),
        ("jpeg", SourceFormat.JPEG),
        ("scan", SourceFormat.PDF),
        ("mixed", SourceFormat.PDF),
        ("overlap", SourceFormat.PDF),
    ],
)
def test_source_pinned_ocr_literal_provenance_and_no_native_duplicates(
    corpus, name, fmt
):
    path = corpus[name]
    data = path.read_bytes()
    digest = sha256(data).hexdigest()
    result = DocumentParser(profile="B_docling").parse(
        VerifiedSource(path, digest, len(data)), fmt
    )
    text = " ".join(item.text for item in result.items)
    for line in GOLDEN:
        assert text.count(line) == 1, (name, text)
    assert result.status == "partial" and any(
        i.code == "ocr_needs_review" for i in result.issues
    )
    assert result.processing_options["ocr_profile"]["download_enabled"] is False
    if name == "mixed":
        assert text.count("Native exact 987") == 1
        assert (
            next(i for i in result.items if i.text == "Native exact 987").text_origin
            == "native"
        )
    if name == "overlap":
        assert any(
            GOLDEN[0] in i.text and i.text_origin in {"native", "mixed"} for i in result.items
        )
        assert all(c["text"] != GOLDEN[0] for c in result.source_metadata["ocr_cells"])
    for picture in result.items:
        if picture.asset_bytes:
            picture.asset_path = "fixture://immutable-image"
    source = SourceVersion(
        id=source_revision_id("w", "d", digest),
        document_id="d",
        workspace_id="w",
        content_sha256=digest,
        storage_uri="fixture://original",
        storage_version="v1",
        byte_size=len(data),
        mime_type=MIME_TYPES[fmt],
        filename=path.name,
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    spec = processing_spec(result)
    snapshot = CanonicalMapper().map(
        result,
        source,
        revision_id=processing_revision_id(source.id, spec),
        created_at=source.recorded_at,
        processing=spec,
        pdf_path=path if fmt is SourceFormat.PDF else None,
    )
    output, _, _, files = output_bundle(snapshot)
    assert (
        output.version == "1.2.0"
        and output.quality.semantic_status == "needs_enrichment"
    )
    ocr_nodes = [
        n
        for n in snapshot.structure
        if n.annotation.provenance.producer_id == "producer-easyocr"
    ]
    assert ocr_nodes and all(
        n.annotation.review_status == "unreviewed" for n in ocr_nodes
    )
    assert all(
        n.annotation.provenance.confidence_method.startswith("easyocr")
        for n in ocr_nodes
    )
    assert result.source_metadata["ocr_cells"]
    if fmt is not SourceFormat.PDF:
        assert all(e.locator.kind == "image_region" for e in snapshot.evidence)
        assert any(a.content_sha256 == digest for a in snapshot.artifacts)
        assert result.source_metadata["image_preparation"]["source_sha256"] == digest
        assert result.source_metadata["image_preparation"]["exif_orientation"] == (
            6 if name == "jpeg" else 1
        )
        assert (
            next(i for i in result.items if i.anchor == "original-image").asset_bytes
            == data
        )
    else:
        assert all(e.locator.kind == "pdf_page" for e in snapshot.evidence)
    assert path.read_bytes() == data
    assert files == output_bundle(snapshot)[3]


def test_blank_image_remains_explicit_partial_with_original_binary(corpus):
    path = corpus["blank"]
    data = path.read_bytes()
    result = DocumentParser(profile="B_docling").parse(
        VerifiedSource(path, sha256(data).hexdigest(), len(data)), SourceFormat.PNG
    )
    assert result.status != "failed"
    assert result.source_metadata["docling_confidence"]
    assert not result.source_metadata["ocr_cells"]
    assert (
        next(i for i in result.items if i.anchor == "original-image").asset_bytes
        == data
    )
