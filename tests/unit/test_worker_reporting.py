"""Stage reporting tests; parser modules are stubbed, no extraction is run."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docgrain_domain import JobStage


@pytest.fixture
def worker(monkeypatch):
    for name in (
        "pymupdf", "docling", "docling.datamodel", "docling.datamodel.base_models",
        "docling.datamodel.pipeline_options", "docling.document_converter",
    ):
        monkeypatch.setitem(sys.modules, name, MagicMock())
    name = "docgrain_worker._reporting_test"
    path = Path(__file__).resolve().parents[2] / "apps/worker/docgrain_worker/main.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_success_does_not_claim_unimplemented_stages_or_measured_timing(worker):
    stages = worker.stage_update(
        [{"stage": stage.value} for stage in JobStage],
        rendered_pages=3, extraction_provider="gemini-test",
    )
    by_stage = {stage["stage"]: stage for stage in stages}
    for stage in ("normalize", "chunk", "enrich", "embed", "vision"):
        assert by_stage[stage]["status"] == "skipped"
    for stage in ("register", "render", "extract", "quality", "publish"):
        assert by_stage[stage]["status"] == "done"
        assert "started_at" not in by_stage[stage]
        assert "finished_at" not in by_stage[stage]
        assert "attempt" not in by_stage[stage]
    assert "no canonical manifest or index" in by_stage["publish"]["summary"]
    assert "not measured" in by_stage["quality"]["summary"]


@pytest.mark.parametrize("failed_stage", ["render", "extract", "publish"])
def test_failure_is_attributed_to_the_operation_that_failed(worker, failed_stage):
    stages = worker.stage_update(
        [{"stage": stage.value} for stage in JobStage],
        "storage or provider failed", failed_stage=failed_stage,
    )
    failures = [stage for stage in stages if stage["status"] == "failed"]
    assert len(failures) == 1
    assert failures[0]["stage"] == failed_stage
    assert failures[0]["error"] == "storage or provider failed"


def test_published_output_reports_real_normalize_and_chunk_but_no_embeddings(worker):
    stages = worker.stage_update([{"stage":stage.value} for stage in JobStage],
        canonical_persisted=True,outputs_published=True,chunk_count=3,output_revision_id="projection-test")
    by_stage = {stage["stage"]:stage for stage in stages}
    assert by_stage["normalize"]["status"] == by_stage["chunk"]["status"] == "done"
    assert by_stage["chunk"]["attributes"]["chunk_count"] == 3
    assert by_stage["embed"]["status"] == by_stage["enrich"]["status"] == "skipped"
    assert "ai.json" in by_stage["publish"]["summary"]
