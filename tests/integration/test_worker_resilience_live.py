"""Opt-in worker-image OCR and isolated PostgreSQL lease/recovery probes."""

import importlib.util
import json
import os
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from docgrain_api import document_jobs
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.conversion_guard import convert
from docgrain_worker.structural import VerifiedSource
from psycopg import sql


@pytest.mark.skipif(importlib.util.find_spec("docling") is None, reason="real Docling requires worker image")
@pytest.mark.parametrize("fmt", [SourceFormat.PNG, SourceFormat.JPEG])
def test_bounded_child_converts_large_source_and_grounds_literal_label(tmp_path, fmt):
    from PIL import Image, ImageDraw, ImageFont

    path = tmp_path / f"synthetic-map.{fmt.value}"
    with Image.new("L", (15000, 8000), "white") as image:
        ImageDraw.Draw(image).text((1500, 1600), "MAP LABEL 127", fill="black", font=ImageFont.load_default(size=240))
        image.save(path, format="PNG" if fmt is SourceFormat.PNG else "JPEG")
    data = path.read_bytes()
    result = convert(VerifiedSource(path, sha256(data).hexdigest(), len(data)), fmt)
    assert result.status != "failed"
    label = next(item for item in result.items if "MAP LABEL 127" in item.text)
    assert (label.locator["width_px"], label.locator["height_px"]) == (15000, 8000)
    # Independent location of the generated literal, in original normalized pixels.
    assert .08 < label.locator["bbox"]["x"] < .12
    assert .18 < label.locator["bbox"]["y"] < .25
    assert label.locator["bbox"]["width"] > .05
    assert any(issue.code == "image_downscaled" for issue in result.issues)
    assert result.source_metadata["image_preparation"]["input_width_px"] <= 6000


@pytest.fixture
def database():
    url = os.getenv("DOCGRAIN_M1_TEST_DATABASE_URL")
    if not url:
        pytest.skip("isolated PostgreSQL requires DOCGRAIN_M1_TEST_DATABASE_URL")
    schema = "wp105_test_" + uuid4().hex
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    def connect():
        conn = psycopg.connect(url)
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        return conn
    try:
        with connect() as conn:
            conn.execute("""CREATE TABLE document_versions (id TEXT PRIMARY KEY, status TEXT);
                CREATE TABLE jobs (id TEXT PRIMARY KEY, document_version_id TEXT, status TEXT,
                    stages JSONB, queued_at TIMESTAMPTZ DEFAULT NOW(), started_at TIMESTAMPTZ,
                    finished_at TIMESTAMPTZ, duration_ms INTEGER);""")
            document_jobs.initialize(conn)
            document_jobs.initialize(conn)  # Compatible with existing DB and repeated startup.
            conn.execute("INSERT INTO document_versions VALUES ('version', 'processing')")
            conn.execute("""INSERT INTO jobs(id, document_version_id, status, stages, started_at)
                VALUES ('job', 'version', 'running', %s::jsonb, NOW()-INTERVAL '16 minutes')""",
                         (json.dumps([{"stage": "extract"}, {"stage": "publish"}]),))
        yield connect
    finally:
        with psycopg.connect(url) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_existing_orphan_requeues_once_and_fences_old_run(database):
    with database() as conn:
        assert document_jobs.recover(conn) == ["job"]
    with database() as conn:
        token = document_jobs.claim(conn, "job")
        assert token and document_jobs.claim(conn, "job") is None
        assert not document_jobs.progress(conn, "job", "old-worker")
        assert document_jobs.progress(conn, "job", token)
        assert document_jobs.recover(conn) == []
        conn.execute("UPDATE jobs SET progress_at=NOW()-INTERVAL '16 minutes'")
    with database() as conn:
        assert document_jobs.recover(conn) == []
        status, retries, stages = conn.execute("SELECT status, stale_retries, stages FROM jobs").fetchone()
        assert status == "failed" and retries == 1
        assert stages[0]["attributes"]["structural_issues"][0]["code"] == "worker_stale"
        assert conn.execute("SELECT status FROM document_versions").fetchone()[0] == "failed"


def test_recovery_skips_locked_running_job(database):
    with database() as first:
        first.execute("SELECT id FROM jobs WHERE id='job' FOR UPDATE")
        with database() as second:
            assert document_jobs.recover(second) == []
    with database() as conn:
        assert document_jobs.recover(conn) == ["job"]
