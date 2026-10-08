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
    verify_installed_options,
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
        assert row["word_recall"] >= 0.8 and row["tables"] >= 1
    elif name.startswith("scan"):
        assert row["blocks"] >= 1
        assert row["word_recall"] is None
    if path.suffix in {".pdf", ".png"}:
        report = row["docling_confidence"]
        assert report["pages"]
        for page in report["pages"].values():
            assert {"ocr_score", "layout_score", "parse_score", "mean_grade", "low_grade"} <= page.keys()


def test_real_benchmark_cli(corpus, tmp_path):
    assert main(["--profiles", "A_current,B_docling", "--root", str(corpus), "--out", str(tmp_path)]) == 0
    rows = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 12 and {row["profile"] for row in rows} == {"A_current", "B_docling"}
    assert "sn/sayfa" in (tmp_path / "profiles.md").read_text(encoding="utf-8")


def test_e_uses_verified_api_options_and_only_hard_pages(monkeypatch, corpus):
    from types import SimpleNamespace

    from docgrain_worker.structural import StructuralParseResult

    monkeypatch.setenv("TEST_PROFILE_VLM_KEY", "synthetic-secret")
    remote = RemoteOptions("https://model.example/v1", "test-model", "TEST_PROFILE_VLM_KEY")
    converter, fmt = build_converter(SourceFormat.PDF, profile="E_vlm", ocr_enabled=True, remote=remote)
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


@pytest.mark.parametrize("name,fmt", [("table", SourceFormat.PDF), ("multicolumn", SourceFormat.PDF),
                                      ("docx-table", SourceFormat.DOCX), ("xlsx", SourceFormat.XLSX)])
def test_a_current_byte_golden_against_frozen_dev_converter(tmp_path, name, fmt):
    """Frozen pre-WP converter construction; compare its actual exported bytes."""
    from tests.fixtures.structural.generate import create_corpus
    verify_installed_options()
    from docgrain_worker.ocr import options
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorOptions,
        PdfPipelineOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    path = create_corpus(tmp_path)[name]
    ocr_enabled = fmt is SourceFormat.PDF
    input_format = InputFormat(fmt.value)
    pipeline = PdfPipelineOptions(do_ocr=ocr_enabled, generate_picture_images=True)
    if ocr_enabled:
        pipeline.ocr_options = options()
        pipeline.accelerator_options = AcceleratorOptions(device="cpu", num_threads=2)
        pipeline.generate_parsed_pages = True
    legacy = DocumentConverter(allowed_formats=[input_format], format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)} if fmt is SourceFormat.PDF else {})
    current, _ = build_converter(fmt, profile="A_current", ocr_enabled=ocr_enabled)
    assert current.format_to_options[input_format].pipeline_options.model_dump(mode="json") == legacy.format_to_options[input_format].pipeline_options.model_dump(mode="json")
    before = legacy.convert(path, raises_on_error=False).document
    after = current.convert(path, raises_on_error=False).document
    assert before.export_to_markdown().encode() == after.export_to_markdown().encode()
    assert json.dumps(before.export_to_dict(), ensure_ascii=False).encode() == json.dumps(after.export_to_dict(), ensure_ascii=False).encode()
    data = path.read_bytes()
    source = VerifiedSource(path, sha256(data).hexdigest(), len(data))
    implicit = DocumentParser(ocr_enabled=True, native_fidelity=True).parse(source, fmt)
    explicit = DocumentParser(ocr_enabled=True, native_fidelity=True, profile="A_current").parse(source, fmt)
    assert implicit == explicit
