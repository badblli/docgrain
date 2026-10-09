"""Stored-version CLI, checkpoints and API dispatch, using isolated fixtures."""

import json
from contextlib import nullcontext
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pymupdf
import pytest
from docgrain_api.settings import get_settings
from docgrain_domain.source_format import SourceFormat
from docgrain_worker import reread
from docgrain_worker.structural import (
    StructuralItem,
    StructuralParseResult,
    VerifiedSource,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from minio.error import S3Error

from tests.unit.test_reading_quality import model

pytest_plugins = ["tests.unit.test_reading_quality"]


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.reads = []

    def put_object(self, bucket, key, data, length, **kwargs):
        self.objects[key] = data.read()
        assert len(self.objects[key]) == length

    def get_object(self, bucket, key, **kwargs):
        self.reads.append((key, kwargs))
        if key not in self.objects:
            raise S3Error(None, "NoSuchKey", "missing", key, "request", "host")
        response = BytesIO(self.objects[key])
        response.release_conn = lambda: None
        response.headers = {}
        return response


@pytest.fixture
def stored_version(tmp_path, monkeypatch):
    # Keep TemporaryDirectory inside this worker's writable worktree on Windows.
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    path = tmp_path / "source.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    data = path.read_bytes()
    version = SimpleNamespace(id="v", document_id="d", workspace_id="w", source_uri="s3://bucket/source.pdf?versionId=receipt",
        content_sha256=sha256(data).hexdigest(), byte_size=len(data), status="partial")
    document = SimpleNamespace(id="d", workspace_id="w", filename="sample.pdf", mime_type="application/pdf")
    source = VerifiedSource(path, version.content_sha256, len(data))
    parsed = StructuralParseResult(SourceFormat.PDF, "docling", "2.130.0", "partial", [
        StructuralItem("paragraph", "unclear", {"page_number": 1}, text="Locally unclear text")],
        ["page:1"], ["page:1"], [], source_metadata={"pages": {"1": {}},
            "docling_confidence": {"pages": {"1": {"low_grade": "poor"}}}}, page_images={1: b"synthetic-page-image"})
    client = MemoryStorage()
    client.objects["source.pdf"] = data
    return document, version, source, parsed, client


def test_persisted_checkpoint_resume_never_reparses(stored_version, monkeypatch, docling_transport):
    document, version, source, parsed, client = stored_version
    first = reread.run_reading(source, workspace_id="w", document_id="d", version_id="v", client=client,
        bucket="bucket", structural=parsed, resolve=lambda *a, **kw: model())
    assert first["pages_read_by_model"] == 1
    key = first["pages"][0]["model_reading"]["proposal_key"]
    proposal = json.loads(client.objects[key])
    assert proposal["review_state"] == "needs_review" and proposal["markdown"] == "Visible text 42"
    assert "synthetic-secret" not in str(client.objects)
    monkeypatch.setattr(reread, "convert", lambda *a, **kw: pytest.fail("Stored report must avoid local reparse"))
    second = reread.reread_version(version, document, client=client, bucket="bucket", resolve=lambda *a, **kw: model())
    assert second["attempted_pages"] == 0 and len(docling_transport.calls) == 1
    assert ("source.pdf", {"version_id": "receipt"}) in client.reads


def test_cli_updates_fixture_report_without_upload(stored_version, monkeypatch, capsys):
    from docgrain_api import storage
    document, version, source, parsed, client = stored_version
    def disabled(*a, **kw):
        from docgrain_api.workspace_settings import ModelSettingsError
        raise ModelSettingsError("Model kapalı.")
    reread.run_reading(source, workspace_id="w", document_id="d", version_id="v", client=client,
        bucket="bucket", structural=parsed, resolve=disabled)
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(get_settings(), "s3_bucket", "bucket")
    monkeypatch.setattr(storage, "storage_client", lambda: client)
    monkeypatch.setattr(reread.repository, "list_documents", lambda: [document, SimpleNamespace(id="other", workspace_id="other")])
    monkeypatch.setattr(reread.repository, "list_versions", lambda: [version])
    conn = SimpleNamespace(execute=lambda *a: None, close=lambda: None)
    monkeypatch.setattr(reread.psycopg, "connect", lambda *a: conn)
    class Reader:
        def __init__(self, *a, **kw):
            pass
        def read(self, *a, **kw):
            return "New visible text 42"
    # Defaults are replaced through the actual run_reading entry point used by the CLI.
    original = reread.read_hard_pages
    monkeypatch.setattr(reread, "read_hard_pages", lambda *a, **kw: original(*a, **kw,
        resolve=lambda *a, **kw: model(), reader_factory=Reader))
    assert reread.main(["--workspace", "w", "--document", "d"]) == 0
    updated = json.loads(client.objects[reread.report_key("d", "v")])
    assert updated["pages_read_by_model"] == 1
    assert "inceleme bekliyor" in capsys.readouterr().out
    assert version.status == "partial"


def test_changed_images_or_source_are_rejected(stored_version, docling_transport):
    document, version, source, parsed, client = stored_version
    reread.run_reading(source, workspace_id="w", document_id="d", version_id="v", client=client,
        bucket="bucket", structural=parsed, resolve=lambda *a, **kw: model())
    client.objects["artifacts/d/v/reading-pages/0001.png"] = b"tampered"
    with pytest.raises(ValueError, match="image verification"):
        reread.reread_version(version, document, client=client, bucket="bucket")
    client.objects["source.pdf"] = b"tampered"
    with pytest.raises(ValueError, match="Source verification"):
        reread.reread_version(version, document, client=client, bucket="bucket")
    assert len(docling_transport.calls) == 1


def test_legacy_version_without_report_runs_local_reader_once(stored_version, monkeypatch, docling_transport):
    document, version, _, parsed, client = stored_version
    calls = []
    monkeypatch.setattr(reread, "convert", lambda *a, **kw: calls.append(a) or parsed)
    updated = reread.reread_version(version, document, client=client, bucket="bucket", resolve=lambda *a, **kw: model())
    assert len(calls) == 1 and updated["pages_read_by_model"] == 1


def api_client(monkeypatch, document, version):
    from docgrain_api.routers import reading_quality as router
    monkeypatch.setattr(router.repository, "get_document", lambda id: document if id == document.id else None)
    monkeypatch.setattr(router.repository, "get_version", lambda d, v: version if d == document.id and v == version.id else None)
    app = FastAPI()
    app.include_router(router.router)
    return TestClient(app), router


def test_report_api_checks_workspace_and_source_identity(stored_version, monkeypatch):
    document, version, source, parsed, _ = stored_version
    client, router = api_client(monkeypatch, document, version)
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    report = reread.reading_report(parsed, document_id="d", version_id="v", workspace_id="w", source_sha256=source.content_sha256)
    monkeypatch.setattr(router, "get_text", lambda *a: json.dumps(report))
    path = "/v1/documents/d/versions/v/reading-quality"
    assert client.get(path + "?workspace_id=w").json()["pages_waiting_model"] == 1
    assert client.get(path + "?workspace_id=other").status_code == 404
    report["source_sha256"] = "0" * 64
    assert client.get(path).status_code == 503


def test_reread_api_only_enqueues_and_demo_is_readonly(stored_version, monkeypatch):
    document, version, *_ = stored_version
    client, router = api_client(monkeypatch, document, version)
    calls = []
    monkeypatch.setattr(router, "dispatch_reread", lambda v: calls.append(v.id) or "job-fake")
    path = "/v1/documents/d/versions/v/reread"
    assert client.post(path).status_code == 409 and calls == []
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    assert client.post(path + "?workspace_id=other").status_code == 404 and calls == []
    response = client.post(path + "?workspace_id=w")
    assert response.status_code == 202 and response.json()["job_id"] == "job-fake"
    assert calls == ["v"]
    version.status = "processing"
    assert client.post(path).status_code == 409


def test_dispatch_persists_worker_marker_and_no_keys(stored_version, monkeypatch):
    _, version, *_ = stored_version
    from docgrain_api.routers import reading_quality as router
    queries, queued = [], []
    rows = iter([(True,), None])
    cur = SimpleNamespace(execute=lambda *a: queries.append(a), fetchone=lambda: next(rows))
    conn = SimpleNamespace(cursor=lambda: nullcontext(cur))
    monkeypatch.setattr(router.repository, "_connection", lambda: nullcontext(conn))
    monkeypatch.setattr(router, "enqueue", queued.append)
    job_id = router.dispatch_reread(version)
    assert queued == [job_id]
    assert "reading_reread" in queries[-1][1][-1] and "synthetic-secret" not in str(queries)
    rows = iter([(True,), ("existing",)])
    cur.fetchone = lambda: next(rows)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        router.dispatch_reread(version)
    assert error.value.status_code == 409 and queued == [job_id]
    cur.fetchone = lambda: (False,)
    with pytest.raises(HTTPException) as error:
        router.dispatch_reread(version)
    assert error.value.status_code == 409 and queued == [job_id]


def test_checkpoint_survives_later_page_failure(stored_version, monkeypatch, docling_transport):
    _, _, source, parsed, client = stored_version
    parsed.expected_areas.append("page:2")
    parsed.page_images[2] = b"second"
    parsed.source_metadata["docling_confidence"]["pages"]["2"] = {"low_grade": "poor"}
    parsed.items.append(StructuralItem("paragraph", "second", {"page_number": 2}, text="Second"))
    original = client.put_object
    def fail_report(bucket, key, *a, **kw):
        if "reading-proposals" in key and len(docling_transport.calls) == 2:
            raise OSError("synthetic-secret")
        return original(bucket, key, *a, **kw)
    monkeypatch.setattr(client, "put_object", fail_report)
    with pytest.raises(OSError):
        reread.run_reading(source, workspace_id="w", document_id="d", version_id="v", client=client,
            bucket="bucket", structural=parsed, resolve=lambda *a, **kw: model())
    checkpoint = json.loads(client.objects[reread.report_key("d", "v")])
    assert checkpoint["pages"][0]["state"] == "needs_review"
    assert checkpoint["pages"][1]["model_reading"] is None


@pytest.mark.parametrize("fail", [False, True])
def test_worker_reread_does_not_parse_or_modify_existing_version(stored_version, monkeypatch, fail):
    from docgrain_worker import main as worker
    document, version, _, _, client = stored_version
    stages = [{"stage": "quality", "attributes": {"reading_reread": True, "previous_version_status": "done"}}]
    row = (version.id, document.id, stages, document.filename, document.mime_type, "w", version.byte_size,
           version.content_sha256, version.source_uri)
    queries = []
    class Cursor:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, *args):
            queries.append(args)
        def fetchone(self):
            return row
    class Connection:
        def cursor(self):
            return Cursor()
        def execute(self, *args):
            queries.append(args)
            return SimpleNamespace(fetchone=lambda: (True,))
        def commit(self):
            pass
        def close(self):
            pass
    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture")
    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setenv("CANONICAL_PERSISTENCE_ENABLED", "false")
    monkeypatch.setattr(worker.psycopg, "connect", lambda *a: Connection())
    monkeypatch.setattr(worker, "storage", lambda: client)
    monkeypatch.setattr(worker, "convert", lambda *a, **kw: pytest.fail("No local reparse"))
    monkeypatch.setattr(worker, "_progress", lambda *a: None)
    def reading(*a, **kw):
        assert kw["structural"] is None
        if fail:
            raise RuntimeError("synthetic-secret")
        return {"summary": "1 sayfa inceleme bekliyor", "pages_waiting_model": 0}
    monkeypatch.setattr(reread, "run_reading", reading)
    worker.process("job-fixture", "token")
    # claim() marked the version processing; the reread restores it and never rewrites the parse.
    updates = [q for q in queries if "UPDATE document_versions" in q[0]]
    assert len(updates) == 1 and "status='processing'" in updates[0][0] and updates[0][1][0] == "done"
    assert "parser" not in updates[0][0]
    job = next(q for q in queries if "UPDATE jobs" in q[0])
    assert job[1][0] == ("failed" if fail else "done")
    assert any("run_token" in q[0] for q in queries)
    assert "synthetic-secret" not in str(queries)
    assert ("source.pdf", {"version_id": "receipt"}) in client.reads


def test_proposal_api_returns_only_source_bound_unapproved_content(stored_version, monkeypatch, docling_transport):
    document, version, source, parsed, storage = stored_version
    reread.run_reading(source, workspace_id="w", document_id="d", version_id="v", client=storage,
        bucket="bucket", structural=parsed, resolve=lambda *a, **kw: model())
    client, router = api_client(monkeypatch, document, version)
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(router, "get_text", lambda key: storage.objects.get(key, b"null").decode())
    path = "/v1/documents/d/versions/v/reading-quality/pages/1/proposal"
    response = client.get(path)
    assert response.status_code == 200 and response.json()["review_state"] == "needs_review"
    assert client.get(path + "?workspace_id=other").status_code == 404
    report = json.loads(storage.objects[reread.report_key("d", "v")])
    report["pages"][0]["model_reading"]["proposal_key"] = "artifacts/another/private.json"
    storage.objects[reread.report_key("d", "v")] = json.dumps(report).encode()
    assert client.get(path).status_code == 503
