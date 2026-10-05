from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

from docgrain_api.main import app
from docgrain_api.routers import outputs
from docgrain_api.settings import get_settings
from docgrain_domain.canonical.ai_output import (
    MIME,
    OutputFile,
    OutputPublication,
    output_bundle,
)
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


def test_context_is_downloadable_and_in_package(monkeypatch):
    snapshot, files = setup(monkeypatch)
    client = TestClient(app)
    base = f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}"
    response = client.get(base + "/outputs/context.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.content == files["context.md"]
    with ZipFile(BytesIO(client.get(base + "/package").content)) as package:
        assert package.read("context.md") == files["context.md"]


def test_historical_package_without_context_stays_downloadable(monkeypatch):
    snapshot, files = setup(monkeypatch)
    publication = outputs._outputs(snapshot.knowledge_revision.id)
    historical = publication.model_copy(update={"files": [item for item in publication.files
                                                        if item.name != "context.md"]})
    monkeypatch.setattr(outputs, "_outputs", lambda _: historical)
    base = f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}"
    client = TestClient(app)
    assert client.get(base + "/outputs/context.md").status_code == 404
    response = client.get(base + "/package")
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as package:
        assert "context.md" not in package.namelist()
        assert package.read("canonical.md") == files["canonical.md"]


def test_corrupted_stored_bytes_return_error_instead_of_success(monkeypatch):
    snapshot,files = setup(monkeypatch)
    files["ai.json"] = b"corrupted"
    response = TestClient(app).get(f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}/outputs/ai.json")
    assert response.status_code == 503


def test_demo_never_generates_common_output(monkeypatch):
    monkeypatch.setattr(get_settings(),"use_fixtures",True)
    monkeypatch.setattr(outputs,"storage_client",lambda:(_ for _ in ()).throw(AssertionError("demo storage call")))
    assert TestClient(app).get("/v1/knowledge/revisions/demo/outputs").status_code == 404
