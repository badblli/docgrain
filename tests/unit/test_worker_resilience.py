"""Generated large pixels, real child exits, and durable document recovery."""

import importlib.metadata
import json
import os
import sys
import time
from contextlib import nullcontext
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pymupdf
import pytest
from docgrain_api import document_jobs
from docgrain_domain.source_format import SourceFormat
from docgrain_worker import docling_profiles, main, structural
from docgrain_worker.conversion_guard import ConversionError, WorkerCrash, isolated_call
from docgrain_worker.image_budget import (
    BudgetedOcr,
    ImageBudget,
    budgeted_pipeline,
    prepare_pdf,
    restore_pdf_geometry,
)
from docgrain_worker.image_geometry import image_locator, prepare_image
from docgrain_worker.pdf_geometry import normalized_pdf_box
from PIL import Image, ImageDraw


def crash_child():
    os._exit(23)


def healthy_child():
    return "next document served"


def hung_child():
    time.sleep(30)


def excessive_memory_child():
    return bytearray(1024 * 1024 * 1024)


@pytest.mark.parametrize("fmt", [SourceFormat.PNG, SourceFormat.JPEG])
def test_15000_by_8000_pixels_reach_parser_with_original_grounding(tmp_path, monkeypatch, fmt):
    stream = BytesIO()
    with Image.new("L", (15000, 8000), "white") as image:
        ImageDraw.Draw(image).rectangle((1500, 1600, 4500, 3200), fill="black")
        image.save(stream, format="PNG" if fmt is SourceFormat.PNG else "JPEG")
    data = stream.getvalue()
    path = tmp_path / f"map.{fmt.value}"
    path.write_bytes(data)
    original_version = importlib.metadata.version
    monkeypatch.setattr(importlib.metadata, "version", lambda n: "2.130.0" if n == "docling" else original_version(n))
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(stdout="tesseract test", stderr=""))
    monkeypatch.setattr(structural, "_bind_ocr_provenance", lambda *a: [])

    def converter(*args, **kwargs):
        def convert(path, **kwargs):
            with Image.open(path) as image:
                assert image.size == (6000, 3200)
                assert image.getpixel((1200, 960)) == (0, 0, 0)
                w, h = image.size
            raw = {"pages": {"1": {"size": {"width": w, "height": h}}},
                "body": {"children": [{"$ref": "#/texts/0"}]},
                "texts": [{"self_ref": "#/texts/0", "text": "Map label", "label": "paragraph",
                    "prov": [{"page_no": 1, "bbox": {"l": 600, "t": 640, "r": 1800, "b": 1280,
                                                         "coord_origin": "TOPLEFT"}}]}]}
            return SimpleNamespace(status="SUCCESS", pages=[], document=SimpleNamespace(
                export_to_dict=lambda: raw, export_to_markdown=lambda: "Map label"))
        return SimpleNamespace(convert=convert, format_to_options={"image": SimpleNamespace(
            pipeline_options=SimpleNamespace(model_dump=lambda **kw: {}))}), "image"

    monkeypatch.setattr(docling_profiles, "build_converter", converter)
    result = structural.DocumentParser().parse(structural.VerifiedSource(path, sha256(data).hexdigest(), len(data)), fmt)
    assert result.status == "partial"
    box = result.items[0].locator
    assert (box["width_px"], box["height_px"]) == (15000, 8000)
    assert box["bbox"] == pytest.approx({"x": .1, "y": .2, "width": .2, "height": .2})
    assert next(i for i in result.items if i.anchor == "original-image").asset_bytes == data
    assert any(i.code == "image_downscaled" and "15000x8000" in i.reason and "6000x3200" in i.reason for i in result.issues)
    assert result.source_metadata["image_preparation"]["scale_x"] == pytest.approx(.4)


def test_megapixel_limit_and_scaled_exif_rotation():
    budget = ImageBudget(longest_side=6000, max_pixels=1_000_000)
    assert budget.size(6000, 6000) == (1000, 1000)
    stream = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    with Image.new("RGB", (300, 200), "white") as image:
        image.save(stream, format="PNG", exif=exif)
    prepared, metadata = prepare_image(stream.getvalue(), budget=ImageBudget(150, 40000))
    with Image.open(BytesIO(prepared)) as image:
        assert image.size == (100, 150)
    # Original box x=.1,y=.2,w=.2,h=.3, rotated clockwise into prepared frame.
    locator = image_locator({"l": 50, "t": 15, "r": 80, "b": 45, "coord_origin": "TOPLEFT"}, (100, 150), metadata)
    assert locator["bbox"] == pytest.approx({"x": .1, "y": .2, "width": .2, "height": .3})


def test_docling_ocr_render_and_inverse_box_use_the_same_bounded_scale():
    events = []
    seen = []
    class Model:
        scale = 3
        def __call__(self, conversion, pages):
            for page in pages:
                size = page._backend.get_size()
                seen.append((round(size.width * self.scale), round(size.height * self.scale)))
                page.box = [600 / self.scale, 1200 / self.scale]
                yield page
    model = Model()
    page = SimpleNamespace(page_no=1, _backend=SimpleNamespace(get_size=lambda: SimpleNamespace(width=6000, height=3200)))
    assert list(BudgetedOcr(model, ImageBudget(), events)(None, [page])) == [page]
    assert seen == [(6000, 3200)]
    assert page.box == [600, 1200] and model.scale == 3
    assert events[0]["original_size"] == [18000, 9600]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_oversize_pdf_native_content_and_original_visible_boxes(tmp_path, rotation):
    original, prepared = tmp_path / "map.pdf", tmp_path / "prepared.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=15000, height=8000)
        page.insert_text((1500, 1600), "Native map label", fontsize=40)
        page.set_rotation(rotation)
        pdf.new_page()
        pdf.save(original)
    geometry = prepare_pdf(original, prepared)
    assert set(geometry) == {1}
    with pymupdf.open(prepared) as pdf:
        assert "Native map label" in pdf[0].get_text()
        size = pdf[0].rect
        assert max(size.width, size.height) <= 6000
        used_box = {"l": size.width * .1, "t": size.height * .2,
                    "r": size.width * .3, "b": size.height * .4, "coord_origin": "TOPLEFT"}
    locator = {"kind": "pdf_raw", "page_number": 1, "bbox": used_box}
    item = structural.StructuralItem("table", "map", deepcopy(locator), page_size=(size.width, size.height),
        cells=[[{"value": "label", "locator": deepcopy(locator)}]])
    result = structural.StructuralParseResult(SourceFormat.PDF, "docling", "test", "complete", [item], [], [], [],
        source_metadata={"ocr_cells": [{"locator": deepcopy(locator)}]})
    restore_pdf_geometry(result, geometry)
    with pymupdf.open(original) as pdf:
        for loc in [item.locator, item.cells[0][0]["locator"], result.source_metadata["ocr_cells"][0]["locator"]]:
            box = normalized_pdf_box(loc["bbox"], item.page_size, pdf[0], frame=loc["frame"])
            assert box.model_dump() == pytest.approx({"x": .1, "y": .2, "width": .2, "height": .2})


def test_real_child_crash_and_timeout_leave_supervisor_available():
    with pytest.raises(WorkerCrash, match="beklenmedik"):
        isolated_call(crash_child)
    assert isolated_call(healthy_child) == "next document served"


def test_child_memory_limit_fails_document_and_next_child_still_serves():
    with pytest.raises(WorkerCrash):
        isolated_call(excessive_memory_child, memory_mb=512)
    assert isolated_call(healthy_child) == "next document served"
    with pytest.raises(WorkerCrash, match="süresi"):
        isolated_call(hung_child, timeout=.2)
    assert isolated_call(healthy_child) == "next document served"


class RecoveryCursor:
    """Small stateful SQL boundary fake; real locking is covered by opt-in PG tests."""
    def __init__(self, jobs):
        self.jobs = jobs
        self.rows = []
        self.rowcount = 0
        self.version_status = None
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, sql, params=()):
        if sql.startswith("SELECT id, document_version_id"):
            self.rows = [(key, "version", deepcopy(j["stages"]), j["stale_retries"]) for key, j in self.jobs.items()
                         if j["status"] == "running" and j["age"] > params[0]]
        elif "SET status='queued', stale_retries=1" in sql:
            self.jobs[params[0]].update(status="queued", stale_retries=1, run_token=None)
        elif "SET status='failed', run_token=NULL" in sql:
            self.jobs[params[1]].update(status="failed", run_token=None, stages=json.loads(params[0]))
        elif sql.startswith("SELECT id FROM jobs"):
            self.rows = [(key,) for key, j in self.jobs.items() if j["status"] == "queued" and j["stale_retries"] > 0]
        elif "UPDATE document_versions" in sql:
            self.version_status = "failed" if "'failed'" in sql else "processing"
        elif "SET status='running'" in sql:
            self.rowcount = int(self.jobs[params[1]]["status"] == "queued")
            if self.rowcount:
                self.jobs[params[1]].update(status="running", run_token=params[0], age=0)
        else:
            raise AssertionError(sql)
    def fetchall(self):
        return self.rows


def test_stale_run_requeues_once_then_fails_and_skips_fresh_uploads():
    jobs = {"stale": {"status": "running", "stale_retries": 0, "age": 901, "run_token": "old",
                      "stages": [{"stage": "extract"}, {"stage": "publish"}]},
            "fresh": {"status": "running", "stale_retries": 0, "age": 899, "stages": []},
            "unconfirmed": {"status": "queued", "stale_retries": 0, "age": 3600, "stages": []}}
    cursor = RecoveryCursor(jobs)
    conn = SimpleNamespace(cursor=lambda: cursor)
    assert document_jobs.recover(conn) == ["stale"]
    assert cursor.version_status == "processing" and jobs["stale"]["run_token"] is None
    assert document_jobs.recover(conn) == ["stale"]  # Redis outage: dispatch is still pending.
    token = document_jobs.claim(conn, "stale")
    assert token and document_jobs.claim(conn, "stale") is None
    jobs["stale"]["age"] = 901
    assert document_jobs.recover(conn) == []
    assert jobs["stale"]["status"] == cursor.version_status == "failed"
    assert jobs["stale"]["stages"][0]["attributes"]["structural_issues"][0]["code"] == "worker_stale"
    assert jobs["fresh"]["status"] == "running" and jobs["unconfirmed"]["status"] == "queued"


def test_child_crash_is_persisted_as_failed_then_next_job_can_run(monkeypatch):
    cursor = MagicMock()
    stages = [{"stage": "extract"}, {"stage": "publish"}]
    cursor.fetchone.return_value = ("version", stages)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(main, "db_url", lambda: "synthetic")
    monkeypatch.setattr(main.psycopg, "connect", lambda _: conn)
    with pytest.raises(WorkerCrash):
        isolated_call(crash_child)
    main.fail("job", "Belge okuma işlemi durdu.", code="worker_crash", token="lease")
    calls = cursor.execute.call_args_list
    assert "status='failed'" in calls[1].args[0]
    persisted = json.loads(calls[1].args[1][0])
    assert persisted[0]["attributes"]["structural_issues"][0]["code"] == "worker_crash"
    assert "document_versions SET status='failed'" in calls[2].args[0]
    assert isolated_call(healthy_child) == "next document served"


def test_old_child_cannot_fail_new_attempt(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    conn = SimpleNamespace(cursor=lambda: nullcontext(cursor), close=lambda: None)
    monkeypatch.setattr(main, "db_url", lambda: "synthetic")
    monkeypatch.setattr(main.psycopg, "connect", lambda _: conn)
    main.fail("job", "stopped", code="worker_crash", token="old-token")
    assert cursor.execute.call_count == 1
    assert "run_token=%s" in cursor.execute.call_args.args[0]


def test_worker_process_handles_child_crash_and_then_processes_next_document(monkeypatch):
    content = b"Map label 127\n"
    state = {"crashed": "running", "next": "running"}
    job_id = "crashed"
    class Cursor:
        row = None
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql, params=()):
            if sql.startswith("SELECT j.document_version_id"):
                self.row = ("version", "document", [{"stage": "extract"}], "map.txt", "text/plain", "workspace",
                            len(content), sha256(content).hexdigest(), "s3://bucket/synthetic-map.txt")
            elif sql.startswith("SELECT document_version_id"):
                self.row = ("version", [{"stage": "extract"}])
            elif sql.startswith("SELECT 1"):
                self.row = (1,)
            elif "UPDATE jobs" in sql:
                if "status='failed'" in sql:
                    state[job_id] = "failed"
                    assert json.loads(params[0])[0]["attributes"]["structural_issues"][0]["code"] == "worker_crash"
                else:
                    state[job_id] = params[0]
        def fetchone(self):
            return self.row
    conn = SimpleNamespace(cursor=Cursor, close=lambda: None, commit=lambda: None)
    monkeypatch.setattr(main, "db_url", lambda: "synthetic")
    monkeypatch.setattr(main.psycopg, "connect", lambda _: conn)
    monkeypatch.setenv("S3_BUCKET", "synthetic")
    monkeypatch.setenv("CANONICAL_PERSISTENCE_ENABLED", "false")
    monkeypatch.setattr(main, "_progress", lambda *args: None)
    monkeypatch.setattr(main, "_lease_active", lambda *args: None)
    def get_object(*args):
        stream = BytesIO(content)
        stream.headers = {}
        stream.release_conn = lambda: None
        return stream
    monkeypatch.setattr(main, "storage", lambda: SimpleNamespace(get_object=get_object))
    real_convert = main.convert
    monkeypatch.setattr(main, "convert", lambda *args, **kw: isolated_call(crash_child))
    main.process(job_id, "lease-one")
    assert state["crashed"] == "failed"
    job_id = "next"
    monkeypatch.setattr(main, "convert", real_convert)
    main.process(job_id, "lease-two")
    assert state["next"] == "partial"  # Canonical persistence is explicitly off in this test.


def error_child():
    raise ValueError("image signature does not match extension")


def test_child_error_keeps_its_message_and_is_not_a_crash():
    with pytest.raises(ConversionError, match="image signature does not match extension") as caught:
        isolated_call(error_child)
    assert not isinstance(caught.value, WorkerCrash)
    assert isolated_call(healthy_child) == "next document served"


def test_budgeted_pipeline_accepts_docling_keyword_and_wraps_ocr(monkeypatch):
    class StandardPdfPipeline:
        def __init__(self, pipeline_options):
            self.pipeline_options = pipeline_options
            self.ocr_model = SimpleNamespace(scale=3)

    module = SimpleNamespace(StandardPdfPipeline=StandardPdfPipeline)
    monkeypatch.setitem(sys.modules, "docling", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "docling.pipeline", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "docling.pipeline.standard_pdf_pipeline", module)
    events = []
    # DocumentConverter._get_pipeline calls pipeline_cls(pipeline_options=...).
    pipeline = budgeted_pipeline(events)(pipeline_options="options")
    assert isinstance(pipeline.ocr_model, BudgetedOcr) and pipeline.ocr_model.scale == 3
    assert pipeline.ocr_model.events is events


def test_capped_ocr_upscale_of_small_photo_is_not_reported(tmp_path, monkeypatch):
    stream = BytesIO()
    with Image.new("RGB", (3000, 2000), "white") as image:
        image.save(stream, format="JPEG")
    data = stream.getvalue()
    path = tmp_path / "photo.jpeg"
    path.write_bytes(data)
    original_version = importlib.metadata.version
    monkeypatch.setattr(importlib.metadata, "version", lambda n: "2.130.0" if n == "docling" else original_version(n))
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(stdout="tesseract test", stderr=""))
    monkeypatch.setattr(structural, "_bind_ocr_provenance", lambda *a: [])

    def converter(*args, raster_events, **kwargs):
        def convert(path, **kwargs):
            # Docling's 3x OCR render (9000x6000) capped back to the source size.
            raster_events.append({"page_number": 1, "original_size": [9000, 6000], "used_size": [3000, 2000],
                                  "scale": 1 / 3, "render_scale": 1.0})
            raw = {"pages": {"1": {"size": {"width": 3000, "height": 2000}}}, "body": {"children": []}, "texts": []}
            return SimpleNamespace(status="SUCCESS", pages=[], document=SimpleNamespace(
                export_to_dict=lambda: raw, export_to_markdown=lambda: ""))
        return SimpleNamespace(convert=convert, format_to_options={"image": SimpleNamespace(
            pipeline_options=SimpleNamespace(model_dump=lambda **kw: {}))}), "image"

    monkeypatch.setattr(docling_profiles, "build_converter", converter)
    result = structural.DocumentParser().parse(
        structural.VerifiedSource(path, sha256(data).hexdigest(), len(data)), SourceFormat.JPEG)
    assert not any(i.code == "image_downscaled" for i in result.issues)
    assert result.source_metadata["raster_preparation"][0]["used_size"] == [3000, 2000]
    assert result.source_metadata["image_preparation"]["downscaled"] is False


def test_lease_check_is_throttled(monkeypatch):
    calls = []
    clock = [100.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main, "_lease_active", lambda *args: calls.append(args))
    tick = main._lease_tick("job", "lease", every=30)
    tick()
    clock[0] += 29
    tick()
    assert calls == []
    clock[0] += 1
    tick()
    assert calls == [("job", "lease")]
