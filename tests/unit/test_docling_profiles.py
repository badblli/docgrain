"""Offline identity, credential gating, geometry and benchmark metric checks."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pymupdf
import pytest
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import (
    processing_revision_id,
    source_revision_id,
)
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.canonical_mapper import CanonicalMapper, _extraction_annotation
from docgrain_worker.canonical_writer import processing_spec
from docgrain_worker.docling_profiles import RemoteOptions, confidence_report, identity
from docgrain_worker.pdf_geometry import normalized_pdf_box
from docgrain_worker.structural import DocumentParser, VerifiedSource, _docling

from benchmarks.docling_profiles import count_vlm_calls, main, source_text, word_recall


def test_explicit_remote_profile_and_credentials_are_required(monkeypatch):
    monkeypatch.delenv("TEST_VLM_KEY", raising=False)
    with pytest.raises(ValueError, match="explicit"):
        DocumentParser(profile="E_vlm")
    remote = RemoteOptions("https://model.example/v1", "model", "TEST_VLM_KEY")
    with pytest.raises(ValueError, match="nonempty"):
        DocumentParser(profile="E_vlm", remote=remote)
    monkeypatch.setenv("TEST_VLM_KEY", "synthetic-secret")
    with pytest.raises(ValueError, match="explicit E_vlm"):
        DocumentParser(remote=remote)
    assert DocumentParser(profile="E_vlm", remote=remote).profile == "E_vlm"
    with pytest.raises(ValueError, match="without credentials"):
        RemoteOptions("https://user:password@model.example/v1", "model", "TEST_VLM_KEY").validate()


def test_digest_is_stable_sensitive_to_options_and_secret_free(monkeypatch):
    remote = RemoteOptions("https://model.example/v1", "model", "TEST_VLM_KEY")
    options = {"pipeline": {"headers": {"Authorization": "Bearer synthetic-secret"}, "do_ocr": True}}
    first = identity("E_vlm", options, remote=remote)
    assert first == identity("E_vlm", {"pipeline": {"do_ocr": True, "headers": {}}}, remote=remote)
    assert "synthetic-secret" not in json.dumps(first)
    assert first != identity("E_vlm", {"do_ocr": False}, remote=remote)
    assert first != identity("D_fullpage", options)
    assert first != identity("E_vlm", options, remote=RemoteOptions(remote.base_url, "other", remote.key_env))


def test_confidence_preserves_docling_grades_and_missing_scores():
    report = {"ocr_score": float("nan"), "mean_grade": "good", "low_grade": "fair",
              "pages": {1: {"ocr_score": 0.3, "layout_score": 0.9, "parse_score": 0.8,
                            "mean_score": 0.7, "low_grade": "poor"}}}
    converted = SimpleNamespace(confidence=SimpleNamespace(model_dump=lambda **kw: report))
    captured = confidence_report(converted)
    assert captured["ocr_score"] is None
    assert captured["pages"]["1"]["low_grade"] == "poor"
    json.dumps(captured, allow_nan=False)
    assert confidence_report(SimpleNamespace()) is None


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("origin", ["TOPLEFT", "BOTTOMLEFT"])
def test_tolerance_is_independent_bounded_and_clips(rotation, origin):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.set_rotation(rotation)
        raw = {"l": -0.3, "r": 100, "t": -0.2, "b": 200, "coord_origin": origin}
        if origin == "BOTTOMLEFT":
            raw.update(t=800.2, b=600)
        assert normalized_pdf_box(raw, (600, 800), page) is None
        box = normalized_pdf_box(raw, (600, 800), page, tolerance_points=0.5)
        assert box is not None
        assert 0 <= box.x < box.x + box.width <= 1
        assert 0 <= box.y < box.y + box.height <= 1
        assert normalized_pdf_box({**raw, "l": -2}, (600, 800), page, tolerance_points=0.5) is None
        assert normalized_pdf_box({**raw, "r": -0.1}, (600, 800), page, tolerance_points=0.5) is None
        assert normalized_pdf_box({**raw, "r": float("inf")}, (600, 800), page, tolerance_points=0.5) is None


def test_current_txt_golden_and_profile_in_spec(tmp_path):
    path = tmp_path / "sample.txt"
    data = b"# Heading\nExample text 42\n"
    path.write_bytes(data)
    source = VerifiedSource(path, sha256(data).hexdigest(), len(data))
    result = DocumentParser().parse(source, SourceFormat.TXT)
    assert [asdict(item) for item in result.items] == [
        {"kind": "heading", "anchor": "chars:0:9", "locator": {"kind": "text_span", "start": 0, "end": 9},
         "text": "# Heading", "level": 1, "cells": [], "asset_path": None, "asset_bytes": None,
         "asset_mime": None, "page_size": None, "line_range": (1, 1), "text_origin": "native",
         "ocr_confidence": None, "source_data": None, "field_locators": {}},
        {"kind": "paragraph", "anchor": "chars:10:25", "locator": {"kind": "text_span", "start": 10, "end": 25},
         "text": "Example text 42", "level": 1, "cells": [], "asset_path": None, "asset_bytes": None,
         "asset_mime": None, "page_size": None, "line_range": (2, 2), "text_origin": "native",
         "ocr_confidence": None, "source_data": None, "field_locators": {}},
    ]
    spec = processing_spec(result)
    assert spec.options["reading_profile"]["id"] == "A_current"
    clipped = DocumentParser(bbox_tolerance=0.5).parse(source, SourceFormat.TXT)
    assert processing_spec(clipped).digest != spec.digest
    assert spec.options["reading_profile"]["option_digest"] != clipped.reading_profile["option_digest"]


def test_recall_counts_repeated_words_and_no_text_layer():
    assert word_recall("A A B C", "A B B C C") == 0.75
    assert word_recall(None, "OCR output") is None
    assert word_recall("", "invented output") is None
    assert word_recall("é", "e\u0301") == 1


def test_synthetic_source_readers(tmp_path):
    from tests.fixtures.structural.docling_profiles import create_profile_corpus
    root = create_profile_corpus(tmp_path)
    company = root / "synthetic"
    assert "CombinedRuns" in source_text(company / "sample.docx", SourceFormat.DOCX)
    assert "0.15" in source_text(company / "sample.xlsx", SourceFormat.XLSX)
    assert "2026-01-02" in source_text(company / "sample.xlsx", SourceFormat.XLSX)
    text = source_text(company / "columns-table.pdf", SourceFormat.PDF)
    assert "Left column" in text and "Right column" in text and "42" in text
    assert source_text(company / "scan.pdf", SourceFormat.PDF) == ""
    assert source_text(company / "scan.png", SourceFormat.PNG) is None


def test_benchmark_cli_in_process_on_txt_and_empty_root(tmp_path):
    company = tmp_path / "sources" / "synthetic"
    company.mkdir(parents=True)
    (company / "sample.txt").write_text("Example 42", encoding="utf-8")
    out = tmp_path / "private-output"
    assert main(["--profiles", "A_current,B_docling", "--root", str(company.parent), "--out", str(out)]) == 0
    rows = json.loads((out / "profiles.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 2 and all(row["word_recall"] == 1 for row in rows)
    assert all(row["vlm_calls"] == 0 and row["peak_rss_bytes"] > 0 for row in rows)
    assert "synthetic/sample.txt" in (out / "profiles.md").read_text(encoding="utf-8")
    assert main(["--root", str(out), "--out", str(tmp_path / "empty")]) == 1


def test_tesseract_provenance_does_not_claim_easyocr():
    annotation = _extraction_annotation("ocr", 0.7, ["e"], engine="tesseract")
    assert annotation.provenance.producer_id == "producer-tesseract"
    assert annotation.provenance.confidence_method == "tesseract-recognition-min:ocr"


def test_http_call_counter_counts_only_selected_endpoint_and_restores_transport(monkeypatch):
    import sys

    def fake_send(session, request, **kwargs):
        return "synthetic-response"
    class Session:
        send = fake_send
    requests = SimpleNamespace(sessions=SimpleNamespace(Session=Session), Session=Session)
    monkeypatch.setitem(sys.modules, "requests", requests)
    remote = RemoteOptions("https://model.example/v1", "model", "TEST_VLM_KEY")
    with count_vlm_calls(remote) as calls:
        session = requests.Session()
        assert session.send(SimpleNamespace(url=remote.endpoint)) == "synthetic-response"
        session.send(SimpleNamespace(url="https://model.example/other"))
        session.send(SimpleNamespace(url=remote.endpoint))
    assert calls[0] == 2
    assert requests.sessions.Session.send is fake_send


def test_benchmark_failure_is_reported_without_source_diagnostics(monkeypatch, tmp_path, capsys):
    from benchmarks import docling_profiles as benchmark
    root = tmp_path / "sources"
    company = root / "synthetic"
    company.mkdir(parents=True)
    (company / "private-name.txt").write_text("Source", encoding="utf-8")
    def fail(*args, **kwargs):
        print("private-name.txt synthetic-secret source contents")
        raise ValueError("synthetic-secret source contents")
    monkeypatch.setattr(benchmark, "measure", fail)
    out = tmp_path / "out"
    assert main(["--root", str(root), "--out", str(out)]) == 1
    captured = capsys.readouterr()
    assert "private-name" not in captured.out + captured.err
    payload = (out / "profiles.json").read_text(encoding="utf-8")
    assert "synthetic-secret" not in payload and "source contents" not in payload
    assert "ValueError" in payload


@pytest.mark.parametrize("profile", ["B_docling", "C_tesseract", "D_fullpage"])
def test_adapter_disables_native_passes_and_stores_confidence(monkeypatch, tmp_path, profile):
    """Test adapter behavior with a controlled conversion; inference is tested in the worker."""
    import importlib.metadata
    import subprocess

    from docgrain_worker import docling_profiles, pdf_fidelity, pdf_reading, structural

    path = tmp_path / "two-pages.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=600, height=800)
        pdf.new_page(width=600, height=800)
        pdf.save(path)
    data = path.read_bytes()
    verified = VerifiedSource(path, sha256(data).hexdigest(), len(data))
    raw = {"pages": {str(n): {"size": {"width": 600, "height": 800}} for n in (1, 2)},
           "body": {"children": [{"$ref": "#/texts/0"}]},
           "texts": [{"self_ref": "#/texts/0", "label": "paragraph", "text": "Literal 42",
                      "prov": [{"page_no": 1, "bbox": {"l": -0.2, "t": 10, "r": 100, "b": 30,
                                                       "coord_origin": "TOPLEFT"}}]}]}
    report = {"mean_grade": "fair", "low_grade": "poor", "pages": {
        1: {"ocr_score": 0.3, "layout_score": 0.9, "parse_score": 0.8, "low_grade": "poor"}}}
    converted = SimpleNamespace(status="SUCCESS", pages=[], document=SimpleNamespace(
        export_to_dict=lambda: raw, export_to_markdown=lambda: "Literal 42"),
        confidence=SimpleNamespace(model_dump=lambda **kw: report))
    pipeline = {"ocr_options": {"model_storage_directory": "local"}}
    converter = SimpleNamespace(convert=lambda *a, **kw: converted, format_to_options={
        "pdf": SimpleNamespace(pipeline_options=SimpleNamespace(model_dump=lambda **kw: pipeline))})
    monkeypatch.setattr(docling_profiles, "build_converter", lambda *a, **kw: (converter, "pdf"))
    monkeypatch.setattr(structural, "_tag_ocr", lambda *a: [])
    monkeypatch.setattr("docgrain_worker.ocr.verified_profile", lambda: {"engine": "easyocr"})
    original_version = importlib.metadata.version
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "2.130.0" if name == "docling" else original_version(name))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="", stderr="tesseract 5.5\n"))
    def forbidden(*args):
        pytest.fail("native pass must be disabled for profiles B-D")
    monkeypatch.setattr(structural, "_pdf_missing_tables", forbidden)
    monkeypatch.setattr(pdf_fidelity, "reconcile_pdf_tables", forbidden)
    monkeypatch.setattr(pdf_reading, "reconcile_reading", forbidden)
    result = _docling(verified, SourceFormat.PDF, profile=profile, native_fidelity=True)
    assert result.processing_options.get("native_source_fidelity") is None
    assert result.reading_profile["id"] == profile
    assert result.source_metadata["docling_confidence"]["pages"]["1"]["ocr_score"] == 0.3
    source = SourceVersion(id=source_revision_id("w", "d", verified.content_sha256),
        document_id="d", workspace_id="w", content_sha256=verified.content_sha256,
        storage_uri="fixture://source", storage_version="1", byte_size=len(data),
        mime_type="application/pdf", filename=path.name, recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    def mapped(parsed):
        spec = processing_spec(parsed)
        return CanonicalMapper().map(parsed, source, revision_id=processing_revision_id(source.id, spec),
            created_at=source.recorded_at, pdf_path=path, processing=spec)
    snapshot = mapped(result)
    assert snapshot.metadata["docling_confidence"] == result.source_metadata["docling_confidence"]
    assert sum(i["code"] == "bbox_unresolved" for i in snapshot.metadata["structural_parse"]["issues"]) == 1
    result.processing_options["bbox_tolerance_points"] = 0.5
    clipped = mapped(result)
    assert not any(i["code"] == "bbox_unresolved" for i in clipped.metadata["structural_parse"]["issues"])
