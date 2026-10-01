from hashlib import sha256
from types import SimpleNamespace

from docgrain_api.main import app
from docgrain_api.routers import outputs
from docgrain_api.settings import get_settings
from docgrain_domain.canonical.ai_output import MIME, OutputFile, OutputPublication, output_bundle
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.fixtures.lifecycle import mapped_snapshot


def setup(monkeypatch):
    snapshot,*_ = mapped_snapshot()
    _,_,revision,files = output_bundle(snapshot)
    prefix = f"knowledge/{snapshot.document_id}/{snapshot.knowledge_revision.id}/{revision.id}/"
    bucket = get_settings().s3_bucket
    publication = OutputPublication(revision=revision,files=[OutputFile(name=name,content_sha256=sha256(data).hexdigest(),
        byte_size=len(data),mime_type=MIME[name],storage_uri=f"s3://{bucket}/{prefix}{name}?versionId=1") for name,data in files.items()])
    monkeypatch.setattr(outputs,"_outputs",lambda identity:publication if identity == snapshot.knowledge_revision.id else missing())
    class Storage:
        def get_object(self,bucket,key,version_id):
            assert version_id == "1" and key.startswith(prefix)
            return SimpleNamespace(read=lambda:files[key[len(prefix):]],close=lambda:None,release_conn=lambda:None)
    monkeypatch.setattr(outputs,"storage_client",lambda:Storage())
    monkeypatch.setattr(outputs,"get_revision",lambda _:snapshot)
    return snapshot,files


def missing():
    raise HTTPException(404,"no published output")


def test_stored_downloads_and_missing_are_explicit(monkeypatch):
    snapshot,files = setup(monkeypatch)
    client = TestClient(app)
    base = f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}"
    assert client.get(base+"/outputs").json()["output"]["version"] == "1.0.0"
    response = client.get(base+"/outputs/ai.json")
    assert response.status_code == 200 and response.content == files["ai.json"]
    assert "attachment" in response.headers["content-disposition"]
    assert client.get(base+"/outputs/anything.json").status_code == 404
    assert client.get("/v1/knowledge/revisions/missing/outputs").status_code == 404


def test_corrupted_stored_bytes_return_error_instead_of_success(monkeypatch):
    snapshot,files = setup(monkeypatch)
    files["ai.json"] = b"corrupted"
    response = TestClient(app).get(f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}/outputs/ai.json")
    assert response.status_code == 503


def test_demo_never_generates_common_output(monkeypatch):
    monkeypatch.setattr(get_settings(),"use_fixtures",True)
    monkeypatch.setattr(outputs,"storage_client",lambda:(_ for _ in ()).throw(AssertionError("demo storage call")))
    assert TestClient(app).get("/v1/knowledge/revisions/demo/outputs").status_code == 404
