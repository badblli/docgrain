"""Real offline profile conversions; requires baked Docling/OCR worker models."""

import importlib.util
import json
from hashlib import sha256

import pytest
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.docling_profiles import (
    RemoteOptions,
    build_converter,
    run_hard_page_vlm,
    safe_options,
)
from docgrain_worker.structural import DocumentParser, VerifiedSource

from benchmarks.docling_profiles import main, measure

pytestmark = pytest.mark.skipif(importlib.util.find_spec("docling") is None,
                                reason="Docling 2.130 worker image required")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    def blocked(*args, **kwargs):
        pytest.fail("profile integration tests must not access the network")
    monkeypatch.setattr(requests.sessions.Session, "send", blocked)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    from tests.fixtures.structural.docling_profiles import create_profile_corpus
    return create_profile_corpus(tmp_path_factory.mktemp("profile-corpus"))


@pytest.mark.parametrize("profile", ["B_docling", "C_tesseract", "D_fullpage"])
@pytest.mark.parametrize("name", ["columns-table.pdf", "scan.pdf", "scan.png", "sample.docx", "sample.xlsx", "sample.txt"])
def test_real_profiles_meaning_and_canonical_confidence(corpus, profile, name):
    path = corpus / "synthetic" / name
    row = measure(path, profile)
    assert row["status"] != "failed"
    assert row["processing_spec"]["options"]["reading_profile"]["id"] == profile
    assert row["vlm_calls"] == 0
    if name == "columns-table.pdf":
        assert row["pages"] == 2 and row["tables"] >= 1
        assert row["word_recall"] >= 0.9
    elif name == "sample.docx":
        assert row["word_recall"] == 1
    elif name == "sample.xlsx":
        assert row["word_recall"] == 1 and row["tables"] >= 1
    elif name == "sample.txt":
        assert row["word_recall"] == 1
    elif name.startswith("scan"):
        assert row["blocks"] >= 1
        assert row["word_recall"] is None
    if path.suffix in {".pdf", ".png"}:
        report = row["docling_confidence"]
        assert report["pages"]
        for page in report["pages"].values():
            assert {"ocr_score", "layout_score", "parse_score", "mean_grade", "low_grade"} <= page.keys()


@pytest.mark.parametrize("name", ["columns-table.pdf", "scan.pdf", "scan.png", "sample.docx", "sample.xlsx", "sample.txt"])
def test_default_synthetic_conversions_preserve_meaning_and_display(corpus, name):
    from datetime import UTC, datetime

    from docgrain_domain.canonical import SourceVersion
    from docgrain_domain.canonical.ai_output import output_bundle
    from docgrain_domain.canonical.lifecycle import (
        processing_revision_id,
        source_revision_id,
    )
    from docgrain_worker.canonical_mapper import CanonicalMapper
    from docgrain_worker.canonical_writer import processing_spec

    from benchmarks.docling_profiles import FORMATS, source_text, word_recall

    path = corpus / "synthetic" / name
    data = path.read_bytes()
    fmt = FORMATS[path.suffix]
    result = DocumentParser().parse(VerifiedSource(path, sha256(data).hexdigest(), len(data)), fmt)
    assert result.status != "failed"
    spec = processing_spec(result)
    assert spec.options["reading_profile"]["id"] == "C_tesseract"
    assert len(spec.options["reading_profile"]["option_digest"]) == 64
    for item in result.items:
        if item.asset_bytes:
            item.asset_path = "fixture://image/" + sha256(item.asset_bytes).hexdigest()
    source = SourceVersion(id=source_revision_id("w", "d", sha256(data).hexdigest()), document_id="d", workspace_id="w",
        content_sha256=sha256(data).hexdigest(), storage_uri="fixture://source", storage_version="1",
        byte_size=len(data), mime_type="application/octet-stream", filename=name,
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    snapshot = CanonicalMapper().map(result, source, revision_id=processing_revision_id(source.id, spec),
        created_at=source.recorded_at, processing=spec, pdf_path=path if fmt is SourceFormat.PDF else None)
    markdown = output_bundle(snapshot)[3]["canonical.md"].decode()
    if fmt in {SourceFormat.DOCX, SourceFormat.XLSX, SourceFormat.TXT}:
        assert word_recall(source_text(path, fmt), markdown) == 1
    if fmt is SourceFormat.XLSX:
        cells = [cell for node in snapshot.structure if node.kind == "table" for row in node.rows for cell in row]
        assert any(c.value == 0.15 and c.display_text == "15%" for c in cells)
        assert any(c.display_text == "2026-01-02" for c in cells)
        assert "15%" in markdown and "2026-01-02" in markdown
    if fmt is SourceFormat.PDF:
        assert set(result.page_images) == set(range(1, len(result.expected_areas) + 1))
    if name == "columns-table.pdf":
        assert any(node.kind == "table" for node in snapshot.structure)
        assert "Left column" in markdown and "Right column" in markdown and "42" in markdown
    if name.startswith("scan"):
        assert any(node.kind == "text_block" for node in snapshot.structure)


def test_real_benchmark_cli(corpus, tmp_path):
    assert main(["--profiles", "C_tesseract,B_docling", "--root", str(corpus), "--out", str(tmp_path)]) == 0
    rows = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 12 and {row["profile"] for row in rows} == {"C_tesseract", "B_docling"}
    assert "sn/sayfa" in (tmp_path / "profiles.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("profile", ["B_docling", "C_tesseract", "D_fullpage"])
def test_pipeline_uses_baked_artifacts(profile):
    from docgrain_worker.docling_models import model_directory

    converter, fmt = build_converter(SourceFormat.PDF, profile=profile)
    options = converter.format_to_options[fmt].pipeline_options
    assert options.artifacts_path == model_directory()
    assert options.layout_options.model_spec.repo_id == "docling-project/docling-layout-heron"
    if options.do_picture_classification:
        assert options.picture_classification_options.repo_id == "docling-project/DocumentFigureClassifier-v2.5"


def test_e_uses_verified_api_options_and_only_hard_pages(monkeypatch, corpus):
    from types import SimpleNamespace

    from docgrain_worker.structural import StructuralParseResult

    monkeypatch.setenv("TEST_PROFILE_VLM_KEY", "synthetic-secret")
    remote = RemoteOptions("https://model.example/v1", "test-model", "TEST_PROFILE_VLM_KEY")
    converter, fmt = build_converter(SourceFormat.PDF, profile="E_vlm", remote=remote)
    options = converter.format_to_options[fmt].pipeline_options
    assert options.enable_remote_services and options.do_picture_description
    assert options.picture_description_options.params["model"] == "test-model"
    assert "synthetic-secret" not in json.dumps(safe_options(options.model_dump(mode="json")))
    # Actual Docling VLM option models, controlled converter transport, no model/network work.
    import docling.document_converter
    selected = []
    def fake_converter(**kwargs):
        def convert(path, *, page_range, **options):
            selected.append(page_range)
            return SimpleNamespace(status="SUCCESS", document=SimpleNamespace(
                export_to_markdown=lambda: "Unapproved page transcription"))
        return SimpleNamespace(convert=convert)
    monkeypatch.setattr(docling.document_converter, "DocumentConverter", fake_converter)
    path = corpus / "synthetic" / "columns-table.pdf"
    data = path.read_bytes()
    source = VerifiedSource(path, sha256(data).hexdigest(), len(data))
    result = StructuralParseResult(SourceFormat.PDF, "docling", "2.130.0", "complete", [], [], [], [],
        source_metadata={"docling_confidence": {"pages": {
            "1": {"low_grade": "excellent"}, "2": {"low_grade": "poor"}}}})
    run_hard_page_vlm(source, result, remote)
    assert selected == [(2, 2)]
    assert result.items == []
    assert result.source_metadata["vlm_page_proposals"][0]["review_state"] == "proposed"
