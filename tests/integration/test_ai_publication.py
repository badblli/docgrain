"""Real four-format worker publication and immutable storage failures, isolated from user data."""

import io
import json
import os
import uuid
from hashlib import sha256

import jsonschema
import psycopg
import pytest
from docgrain_api import repository as metadata
from docgrain_api.canonical_repository import CanonicalConflict, CanonicalRepository
from docgrain_api.output_repository import OutputRepository
from docgrain_domain.canonical.ai_output import AIOutput, OutputPublication, output_bundle
from docgrain_worker.output_writer import publish_outputs
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.fixtures.lifecycle import mapped_snapshot
from tests.integration import test_m2a_repository as m2a_fixtures

lifecycle_store = m2a_fixtures.lifecycle_store
real_corpus = m2a_fixtures.real_corpus


@pytest.fixture
def output_bucket():
    if not os.environ.get("DOCGRAIN_M2G_TEST_S3"):
        pytest.skip("set DOCGRAIN_M2G_TEST_S3 for unique versioned MinIO output test")
    from docgrain_api.storage import storage_client
    from minio.versioningconfig import ENABLED, VersioningConfig
    client = storage_client()
    bucket = "ai-output-test-" + uuid.uuid4().hex
    client.make_bucket(bucket)
    client.set_bucket_versioning(bucket,VersioningConfig(ENABLED))
    try:
        yield client,bucket
    finally:
        for obj in client.list_objects(bucket,recursive=True,include_version=True):
            client.remove_object(bucket,obj.object_name,version_id=obj.version_id)
        client.remove_bucket(bucket)


def test_partial_storage_failure_retry_hash_guard_and_immutable_sql(lifecycle_store, output_bucket):
    repo,connect,schema = lifecycle_store
    client,bucket = output_bucket
    snapshot,*_ = mapped_snapshot()
    repo.append(snapshot,expected_latest_revision_id=None)
    outputs = OutputRepository(connect,schema)
    class FailPut:
        def __init__(self):
            self.calls = 0
        def __getattr__(self,name):
            return getattr(client,name)
        def put_object(self,*args,**kwargs):
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError("storage failure")
            return client.put_object(*args,**kwargs)
    with pytest.raises(RuntimeError):
        publish_outputs(repo,snapshot,FailPut(),bucket)
    assert outputs.get_outputs(snapshot.knowledge_revision.id) is None
    output,publication,inserted = publish_outputs(repo,snapshot,client,bucket)
    assert inserted and output.quality.measurements["chunks"] == 1
    assert not publish_outputs(repo,snapshot,client,bucket)[2]
    original = snapshot.model_dump(mode="json")
    assert repo.get_snapshot(snapshot.knowledge_revision.id).model_dump(mode="json") == original
    forged = publication.model_dump(mode="json")
    forged["files"][0]["content_sha256"] = "0"*64
    with pytest.raises(CanonicalConflict,match="checksum"):
        outputs.publish_outputs(OutputPublication.model_validate(forged))
    with pytest.raises(psycopg.errors.RaiseException), connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(schema,"knowledge_outputs")))
    # A later overwrite cannot change the immutable version referenced by publication.
    from urllib.parse import urlparse,parse_qs
    file = publication.files[0]
    uri = urlparse(file.storage_uri)
    client.put_object(bucket,uri.path.lstrip("/"),io.BytesIO(b"changed"),7)
    response = client.get_object(bucket,uri.path.lstrip("/"),version_id=parse_qs(uri.query)["versionId"][0])
    try:
        assert sha256(response.read()).hexdigest() == file.content_sha256
    finally:
        response.close()
        response.release_conn()


@pytest.fixture
def worker_store(output_bucket,monkeypatch):
    database = os.environ.get("DOCGRAIN_M1_TEST_DATABASE_URL")
    if not database:
        pytest.skip("isolated PostgreSQL required")
    pytest.importorskip("docling")
    schema = "ai_worker_" + uuid.uuid4().hex
    with psycopg.connect(database) as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped = make_conninfo(database,options=f"-c search_path={schema}")
    def connect():
        return psycopg.connect(scoped)
    from docgrain_api.settings import get_settings
    from docgrain_worker import main as worker
    client,bucket = output_bucket
    monkeypatch.setattr(get_settings(),"use_fixtures",False)
    monkeypatch.setattr(get_settings(),"canonical_persistence_enabled",True)
    monkeypatch.setattr(get_settings(),"s3_bucket",bucket)
    monkeypatch.setattr(metadata,"_database_url",lambda:scoped)
    monkeypatch.setattr(worker,"db_url",lambda:scoped)
    monkeypatch.setattr(worker,"storage",lambda:client)
    monkeypatch.setattr(worker,"CanonicalRepository",lambda factory:CanonicalRepository(factory,schema))
    monkeypatch.setenv("CANONICAL_PERSISTENCE_ENABLED","true")
    monkeypatch.setenv("S3_BUCKET",bucket)
    monkeypatch.setenv("GEMINI_API_KEY","")
    try:
        metadata.initialize()
        repo = CanonicalRepository(connect,schema)
        repo.initialize()
        yield worker,repo,client,bucket,connect
    finally:
        with psycopg.connect(database) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("name,mime",[("table","application/pdf"),("image-heavy","application/pdf"),("docx-headings","application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                                     ("txt-multilingual","text/plain"),("xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                                     ("png-printed","image/png"),("jpeg-printed","image/jpeg")])
def test_real_worker_automatically_publishes_same_ai_contract(worker_store,real_corpus,name,mime,monkeypatch):
    worker,repo,client,bucket,connect = worker_store
    path = real_corpus[name]
    data = path.read_bytes()
    client.put_object(bucket,"uploads/doc-test/version-test/original",io.BytesIO(data),len(data),content_type=mime)
    from docgrain_domain import JobStage
    stages = json.dumps([{"stage":stage.value} for stage in JobStage])
    with connect() as connection,connection.cursor() as cursor:
        cursor.execute("INSERT INTO documents VALUES ('doc-test','workspace-test','AI test',%s,%s,'version-test',1,now(),now())",(path.name,mime))
        cursor.execute("""INSERT INTO document_versions VALUES ('version-test','doc-test','workspace-test',1,%s,%s,%s,0,0,0,0,'processing',NULL,NULL,now(),NULL)""",
                       (sha256(data).hexdigest(),f"s3://{bucket}/uploads/doc-test/version-test/original",len(data)))
        cursor.execute("""INSERT INTO jobs VALUES ('job-test','doc-test','version-test','workspace-test','running',%s::jsonb,'[]'::jsonb,now(),now(),NULL,NULL,NULL)""",(stages,))
    worker.process("job-test")  # actual public worker function, no model/embedder fixture substituted
    with connect() as connection,connection.cursor() as cursor:
        cursor.execute("SELECT status,stages FROM jobs WHERE id='job-test'")
        status,stages = cursor.fetchone()
    assert status in {"done","partial"}, [s for s in stages if s.get("error")]
    assert {s["stage"]:s["status"] for s in stages}["normalize"] == "done"
    assert {s["stage"]:s["status"] for s in stages}["chunk"] == "done"
    head = repo.get_heads("doc-test")[0]
    snapshot = repo.get_snapshot(head)
    publication = OutputRepository(repo._connect,repo._schema).get_outputs(head)
    assert publication is not None
    output,chunks,_,files = output_bundle(snapshot)
    jsonschema.Draft202012Validator(AIOutput.model_json_schema()).validate(json.loads(files["ai.json"]))
    assert {n.id:n.model_dump(mode="json") for n in output.content} == {n.id:n.model_dump(mode="json") for n in snapshot.structure}
    assert output.evidence == snapshot.evidence
    if name in {"png-printed", "jpeg-printed"}:
        assert output.version == "1.2.0"
        assert snapshot.schema_version == "0.6.0"
        assert any(a.content_sha256 == sha256(data).hexdigest() for a in snapshot.artifacts)
        assert all(e.locator.kind == "image_region" for e in snapshot.evidence)
        assert "OCR" in files["ai.json"].decode() or "ocr" in files["ai.json"].decode()
    assert publication.version == "1.0.0"
    if name == "image-heavy":
        assert not chunks.chunks and not output.quality.text_only_complete
        assert "no_text_or_table_content" in {g.code for g in output.quality.gaps}
    else:
        assert chunks.chunks
    if name == "txt-multilingual":
        assert "İzmir 🌊" in files["canonical.md"].decode() and "日本語" in files["canonical.md"].decode()
    if name == "xlsx":
        assert "formula_result_unavailable" in {g.code for g in output.quality.gaps}
    if output.assets:
        assert "missing_visual_description" in {g.code for g in output.quality.gaps}
    # Actual stored API/ZIP path against this isolated revision/bucket.
    from docgrain_api.main import app
    from docgrain_api.routers import knowledge,outputs
    from fastapi.testclient import TestClient
    monkeypatch.setattr(knowledge,"_store",lambda:repo)
    monkeypatch.setattr(outputs,"_store",lambda:repo)
    monkeypatch.setattr(outputs,"storage_client",lambda:client)
    response = TestClient(app).get(f"/v1/knowledge/revisions/{head}/outputs")
    assert response.status_code == 200 and response.json()["output"]["version"] == output.version
    package = TestClient(app).get(f"/v1/knowledge/revisions/{head}/package")
    assert package.status_code == 200
    from zipfile import ZipFile
    with ZipFile(io.BytesIO(package.content)) as bundle:
        assert bundle.read("ai.json") == files["ai.json"]
        for asset in output.assets:
            assert sha256(bundle.read(asset.file)).hexdigest() == asset.artifact.content_sha256
