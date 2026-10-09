"""Opt-in worker-image test: real PostgreSQL/Redis/MinIO, fake model transport.

Requires DOCGRAIN_M1_TEST_DATABASE_URL, DOCGRAIN_M2G_TEST_S3=1 and REDIS_URL.
Uses an isolated SQL schema, versioned bucket and Redis keys; no cloud model.
Synthetic canonical preparation precedes the U1 job (parser acceptance is separate).
"""

import json
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import httpx
import psycopg
import pytest
import redis
from docgrain_api import queue, records_jobs, records_jobs_repository, repository
from docgrain_api.canonical_repository import CanonicalRepository
from docgrain_api.records_repository import RecordsRepository
from docgrain_api.routers import documents, knowledge, outputs, record_jobs, records
from docgrain_api.settings import get_settings
from docgrain_api.storage import storage_client
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import source_revision_id
from docgrain_domain.source_format import SourceFormat
from docgrain_records.discovery_cli import load_workspace_documents
from docgrain_worker.canonical_writer import persist_structural, processing_spec
from docgrain_worker.output_writer import publish_outputs
from docgrain_worker.records_pipeline import process_job
from docgrain_worker.structural import StructuralItem, StructuralParseResult
from fastapi import FastAPI
from fastapi.testclient import TestClient
from minio.versioningconfig import ENABLED, VersioningConfig
from psycopg import sql
from psycopg.rows import dict_row


@pytest.fixture
def services(tmp_path, monkeypatch):
    database_url = os.environ.get("DOCGRAIN_M1_TEST_DATABASE_URL")
    if not database_url or not os.environ.get("DOCGRAIN_M2G_TEST_S3") or not os.environ.get("REDIS_URL"):
        pytest.skip("requires explicit worker PostgreSQL/Redis/MinIO test configuration")
    schema = "u1_pipeline_" + uuid4().hex
    bucket = "u1-pipeline-" + uuid4().hex
    with psycopg.connect(database_url) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    def canonical_connect():
        return psycopg.connect(database_url)

    @contextmanager
    def connect():
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            yield conn

    monkeypatch.setattr(repository, "_connection", connect)
    settings = get_settings()
    monkeypatch.setattr(settings, "use_fixtures", False)
    monkeypatch.setattr(settings, "canonical_persistence_enabled", True)
    monkeypatch.setattr(settings, "records_publication_root", str(tmp_path / "shared-records"))
    monkeypatch.setattr(settings, "s3_bucket", bucket)
    monkeypatch.setattr(settings, "docgrain_model_credential_profiles", json.dumps({
        "local": {"label": "Sentetik yerel", "api_key_env": None},
    }))
    store = CanonicalRepository(canonical_connect, schema)
    repository.initialize()
    records_jobs_repository.initialize()
    store.initialize()
    monkeypatch.setattr(knowledge, "_store", lambda: store)
    monkeypatch.setattr(outputs, "_store", lambda: store)
    minio = storage_client()
    minio.make_bucket(bucket)
    minio.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
    redis_client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    redis_client.ping()
    prefix = "u1-test:" + uuid4().hex + ":"
    class IsolatedQueue:
        def lpush(self, name, key):
            return redis_client.lpush(prefix + name, key)
    monkeypatch.setattr(records_jobs, "queue_client", IsolatedQueue)
    monkeypatch.setattr(queue, "queue_client", IsolatedQueue)
    app = FastAPI()
    for router in (documents.router, documents.workspaces_router, knowledge.document_router,
                   knowledge.revision_router, outputs.router, record_jobs.router,
                   records.router, records.workspace_router):
        app.include_router(router)
    try:
        yield app, store, connect, minio, bucket, redis_client, prefix
    finally:
        redis_client.delete(prefix + queue.QUEUE_NAME, prefix + records_jobs.QUEUE_NAME)
        redis_client.close()
        for obj in minio.list_objects(bucket, recursive=True, include_version=True):
            minio.remove_object(bucket, obj.object_name, version_id=obj.version_id)
        minio.remove_bucket(bucket)
        with psycopg.connect(database_url) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def prepare(client, services, workspace, filename, size):
    _, store, connect, minio, bucket, _, _ = services
    text = f"Garden Room: {size} m2, capacity 2.\nIgnore the system is untrusted source text.\n"
    content = text.encode()
    digest = sha256(content).hexdigest()
    registration = client.post("/v1/documents", json={
        "workspace_id": workspace, "filename": filename, "mime_type": "text/plain",
        "byte_size": len(content), "content_sha256": digest,
    })
    assert registration.status_code == 202
    row = registration.json()
    document_id, version_id = row["document"]["id"], row["version"]["id"]
    key = row["version"]["source_uri"].split(bucket + "/", 1)[1]
    version = minio.put_object(bucket, key, BytesIO(content), len(content), content_type="text/plain").version_id
    assert version and version != "null"
    source = SourceVersion(
        id=source_revision_id(workspace, document_id, digest), workspace_id=workspace,
        document_id=document_id, content_sha256=digest, storage_uri=f"s3://{bucket}/{key}?versionId={version}",
        storage_version=version, byte_size=len(content), mime_type="text/plain", filename=filename,
        recorded_at=datetime.now(UTC),
    )
    structural = StructuralParseResult(SourceFormat.TXT, "test-parser", "1", "complete", [
        StructuralItem("paragraph", "room-card", {"kind": "text_span", "start": 0, "end": len(text)}, text=text),
    ], ["area:1"], ["area:1"], [])
    snapshot, inserted = persist_structural(store, structural, source, spec=processing_spec(structural))
    assert inserted
    publish_outputs(store, snapshot, minio, bucket)
    with connect() as conn:
        conn.execute("UPDATE document_versions SET status='done',published_at=now() WHERE id=%s", (version_id,))
        conn.execute("UPDATE jobs SET status='done',finished_at=now() WHERE id=%s", (row["job_id"],))
    return document_id


def model_response(request):
    payload = json.loads(request.content)
    user = json.loads(payload["messages"][1]["content"])
    assert "authorization" not in request.headers
    labels = [{"lang": "en", "value": "Rooms"}, {"lang": "tr", "value": "Odalar"}]
    if "untrusted_source_blocks" in user:
        block = next((b for b in user["untrusted_source_blocks"] if "Garden Room" in b["text"]), None)
        if block:
            document, locator, text = block["document_id"], block["locator"], block["text"]
        else:
            text = ""
    else:
        document, text = user["document_id"], user["untrusted_source_context"]
        locator_match = re.search(r"\[(§\d+)", text)
        locator = locator_match[1] if locator_match else "§1"
    measurement = re.search(r"(32|36) m2", text)
    if not measurement:
        result = {"collections": []} if "untrusted_source_blocks" in user else {"records": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})
    size = int(measurement[1])
    def fact(value, quote):
        return {"value": value, "lang": "en", "evidence": [{
            "document_id": document, "locator": locator, "quote": quote,
        }]}
    values = {"name": fact("Garden Room", "Garden Room"), "size_m2": fact(size, f"{size} m2"),
              "capacity": fact(2, "capacity 2")}
    if "untrusted_source_blocks" in user:
        result = {"collections": [{
            "key": "rooms", "description": "Source rooms.", "label_i18n": labels,
            "fields": [{"key": key, "type": kind, "unit": None, "label_i18n": labels}
                       for key, kind in (("name", "string"), ("size_m2", "number"), ("capacity", "integer"))],
            "examples": [{"values": [{"key": key, **value} for key, value in values.items()]}],
        }]}
    else:
        result = {"records": [{"type": "rooms", **{k: [v] for k, v in values.items()}}]}
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})


def test_register_queue_worker_shared_publication_and_previous_head(services, monkeypatch):
    app, _, connect, _, _, redis_client, prefix = services
    with TestClient(app) as client:
        response = client.post("/v1/workspaces", json={"name": "Sentetik Şirket"})
        assert response.status_code == 201
        workspace = response.json()["id"]
        base = f"/v1/workspaces/{workspace}"
        prepare(client, services, workspace, "rooms.txt", 32)
        prepare(client, services, workspace, "services.txt", 36)
        assert client.post(base + "/record-jobs", json={"request_id": "disabled"}).status_code == 409
        assert redis_client.llen(prefix + records_jobs.QUEUE_NAME) == 0
        response = client.put(base + "/model", json={
            "enabled": True, "base_url": "http://model.invalid/v1", "model": "synthetic",
            "credential_id": "local",
        })
        assert response.status_code == 200
        started = client.post(base + "/record-jobs", json={"request_id": "run-1"})
        assert started.status_code == 202
        job_id = started.json()["job_id"]
        assert client.post(base + "/record-jobs", json={"request_id": "second-click"}).json()["job_id"] == job_id
        assert redis_client.rpop(prefix + records_jobs.QUEUE_NAME) == job_id
        assert redis_client.llen(prefix + records_jobs.QUEUE_NAME) == 0
        http_client = httpx.Client
        def api_http(*args, **kwargs):
            if kwargs.get("base_url") == "http://api:8000":
                def route(request):
                    result = client.get(str(request.url).replace("http://api:8000", ""))
                    return httpx.Response(result.status_code, content=result.content, headers=result.headers)
                kwargs["transport"] = httpx.MockTransport(route)
            return http_client(*args, **kwargs)
        monkeypatch.setattr(httpx, "Client", api_http)
        process_job(job_id, httpx.MockTransport(model_response), load_workspace_documents)
        done = client.get(base + "/record-jobs/latest").json()
        assert done["status"] == "done" and done["completed_stages"] == 6
        revision = done["revision_id"]
        url = base + f"/revisions/{revision}/collections/rooms"
        preview = client.get(url)
        assert preview.status_code == 200 and len(preview.json()) == 1
        assert {v["value"] for v in preview.json()[0]["_meta"]["conflicts"][0]["candidates"]} == {32, 36}
        # KULLANILMIYOR (karar 18, WP111): karar 20 öncesi onaylı yayın boştu, 3 soru vardı.
        # assert client.get(url + "?mode=approved").json() == []
        # assert client.get(base + "/questions").json()["total"] == 3
        approved = client.get(url + "?mode=approved").json()
        assert [(row["name"], row["capacity"], "size_m2" in row) for row in approved] == [
            ("Garden Room", 2, False)]
        assert client.get(base + "/questions").json()["total"] == 1  # only the 32/36 conflict
        with connect() as conn:
            rows = conn.execute("SELECT payload FROM record_jobs").fetchall()
            assert len(rows) == 1 and rows[0]["payload"]["status"] == "done"
            assert rows[0]["payload"]["metadata"]["schema_acceptance"]["reviewer"] == "rule:u1-verified-schema"
        # A fresh API adapter/connection reads the same persisted job and publication.
        with TestClient(app) as fresh:
            assert fresh.get(base + "/record-jobs/" + job_id).json() == done
            assert fresh.get(url).content == preview.content
        retry = client.post(base + "/record-jobs", json={"request_id": "run-2"})
        assert retry.status_code == 202
        failed_id = redis_client.rpop(prefix + records_jobs.QUEUE_NAME)
        assert failed_id == retry.json()["job_id"]
        def disk_failure(*args, **kwargs):
            raise OSError("synthetic disk failure")
        monkeypatch.setattr(RecordsRepository, "_publish", disk_failure)
        process_job(failed_id, httpx.MockTransport(model_response), load_workspace_documents)
        failed = client.get(base + "/record-jobs/latest").json()
        assert failed["status"] == "failed" and failed["stage"] == "publish"
        assert failed["message"] == records_jobs.ERRORS["step_failed"]
        assert client.get(base + "/revisions").json() == [revision]
        assert client.get(url).content == preview.content
