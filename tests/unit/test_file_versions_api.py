"""WP124 upload contract and live Docling diff API; isolated storage/metadata."""

import json
from hashlib import sha256

import pytest
from docgrain_api import repository
from docgrain_api.main import app
from docgrain_api.routers import documents, versions
from fastapi.testclient import TestClient
from test_file_version_diff import doc

client = TestClient(app)


@pytest.fixture
def uploads(live_repository, monkeypatch):
    stored = {}
    monkeypatch.setattr(documents.format_capabilities, "ensure_format_enabled", lambda fmt: fmt)
    monkeypatch.setattr(documents, "object_exists", lambda key: key in stored)
    monkeypatch.setattr(documents, "put_upload", lambda key, body, mime, length: stored.update({key: body.read()}))
    monkeypatch.setattr(documents, "enqueue", lambda _: None)

    def add_version(document, version, job):
        live_repository["versions"][version.id] = version
        live_repository["jobs"][job.id] = job
        document.version_count += 1

    monkeypatch.setattr(repository, "add_version", add_version)
    return live_repository, stored


def payload(text="Delivery takes three days.", filename="guide.txt"):
    data = text.encode()
    return {"workspace_id": "ws_synthetic", "filename": filename, "mime_type": "text/plain",
            "byte_size": len(data), "content_sha256": sha256(data).hexdigest()}


def first_version(uploads):
    response = client.post("/v1/documents", json=payload())
    assert response.status_code == 202
    result = response.json()
    records, _ = uploads
    records["versions"][result["version"]["id"]].status = "done"
    records["jobs"][result["job_id"]].status = "done"
    return result


def test_new_version_same_document_pending_status_renamed_upload_and_confirmation(uploads):
    original = first_version(uploads)
    document_id = original["document"]["id"]
    metadata = payload("Delivery takes four days.", "new-guide.txt")
    metadata.pop("workspace_id")  # Workspace is inherited; the original shape is also accepted.
    response = client.post(f"/v1/documents/{document_id}/versions", json=metadata)
    assert response.status_code == 202
    result = response.json()
    assert result["document"]["id"] == result["version"]["document_id"] == document_id
    assert result["version"]["revision"] == result["document"]["version_count"] == 2
    assert result["version"]["workspace_id"] == "ws_synthetic"
    assert result["version"]["filename"] == "new-guide.txt"
    assert result["document"]["title"] == "guide"
    assert result["document"]["latest_version_id"] == original["version"]["id"]
    assert len(uploads[0]["documents"]) == 1
    path = f"/v1/documents/{document_id}/versions/{result['version']['id']}"
    assert client.put(f"{path}/content", files={"file": (
        "new-guide.txt", b"Delivery takes four days.", "text/plain")}).status_code == 201
    assert client.post(f"{path}/uploaded").json()["job_id"] == result["job_id"]
    listed = client.get(f"/v1/documents/{document_id}/versions").json()
    assert next(v for v in listed if v["revision"] == 2)["status"] == "processing"
    uploads[0]["versions"][result["version"]["id"]].status = "failed"
    uploads[0]["jobs"][result["job_id"]].status = "failed"
    assert client.get(f"/v1/documents/{document_id}").json()["latest_version"]["id"] == original["version"]["id"]


def test_same_sha_is_deduplicated_and_other_format_rejected(uploads):
    original = first_version(uploads)
    path = f"/v1/documents/{original['document']['id']}/versions"
    response = client.post(path, json=payload(filename="renamed.txt"))
    assert response.status_code == 202 and response.json()["deduplicated"]
    assert response.json()["version"]["id"] == original["version"]["id"]
    assert len(uploads[0]["versions"]) == 1
    assert client.post(path, json={**payload(), "filename": "sheet.xlsx",
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}).status_code == 415
    assert client.post(path, json={**payload(), "workspace_id": "ws_other"}).status_code == 400
    assert client.post("/v1/documents/missing/versions", json=payload()).status_code == 404


def test_different_documents_do_not_share_version_dedup_and_revert_creates_revision(uploads):
    original = first_version(uploads)
    another = client.post("/v1/documents", json=payload("Other text")).json()
    result = client.post(f"/v1/documents/{another['document']['id']}/versions", json=payload()).json()
    assert result["deduplicated"] is False
    assert result["version"]["document_id"] == another["document"]["id"]
    path = f"/v1/documents/{original['document']['id']}/versions"
    second = client.post(path, json=payload("Delivery takes four days.")).json()
    records = uploads[0]
    records["versions"][second["version"]["id"]].status = "done"
    records["documents"][original["document"]["id"]].latest_version_id = second["version"]["id"]
    reverted = client.post(path, json=payload()).json()
    assert not reverted["deduplicated"] and reverted["version"]["revision"] == 3


def test_live_diff_contains_units_counts_and_retains_compatibility_fields(uploads, monkeypatch):
    original = first_version(uploads)
    result = client.post(f"/v1/documents/{original['document']['id']}/versions",
                         json=payload("Delivery takes four days.")).json()
    version_id = result["version"]["id"]
    base = original["version"]["id"]
    path = f"/v1/versions/{version_id}/diff?base={base}"
    assert client.get(path).status_code == 409
    uploads[0]["versions"][version_id].status = "done"
    monkeypatch.setattr(versions, "get_text", lambda key: json.dumps(doc(
        "Delivery takes four days." if version_id in key else "Delivery takes three days.")))
    response = client.get(path)
    assert response.status_code == 200
    diff = response.json()
    assert diff["changed_units"] == 1 and diff["has_changes"]
    assert diff["changes"][0]["before"] == "Delivery takes three days."
    assert diff["changes"][0]["after"] == "Delivery takes four days."
    assert diff["entries"] == [] and diff["chunk_delta"] == diff["table_delta"] == 0
    assert diff["base_version_id"] == base and diff["head_version_id"] == version_id
    monkeypatch.setattr(versions, "get_text", lambda _: None)
    monkeypatch.setattr(versions, "_store", lambda: pytest.fail("not configured"))
    from docgrain_api.settings import get_settings
    monkeypatch.setattr(get_settings(), "canonical_persistence_enabled", False)
    assert client.get(path).status_code == 409  # Missing input is never an empty diff.


def test_old_failed_revision_is_not_reused_and_txt_xml_are_different_families(uploads):
    original = first_version(uploads)
    path = f"/v1/documents/{original['document']['id']}/versions"
    failed = client.post(path, json=payload("Delivery takes five days.")).json()
    records = uploads[0]
    records["versions"][failed["version"]["id"]].status = "failed"
    records["jobs"][failed["job_id"]].status = "failed"
    newer = client.post(path, json=payload("Delivery takes six days.")).json()
    records["versions"][newer["version"]["id"]].status = "done"
    records["documents"][original["document"]["id"]].latest_version_id = newer["version"]["id"]
    # The failed revision 2 is older than latest revision 3: it could never become latest.
    again = client.post(path, json=payload("Delivery takes five days.")).json()
    assert not again["deduplicated"] and again["version"]["revision"] == 4
    assert client.post(path, json={**payload(), "filename": "guide.xml",
                                   "mime_type": "application/xml"}).status_code == 415


def test_knowledge_stays_on_latest_usable_version_while_newer_parse_is_head(monkeypatch):
    from types import SimpleNamespace

    from docgrain_api.routers import knowledge
    from test_knowledge_api import setup_live

    first, store = setup_live(monkeypatch)
    head = first.model_copy(update={
        "knowledge_revision": first.knowledge_revision.model_copy(update={
            "id": "revision-of-version-2", "parent_revision_id": first.knowledge_revision.id}),
        "source_version": first.source_version.model_copy(update={"content_sha256": "b" * 64}),
    })
    snapshots = {s.knowledge_revision.id: s for s in (first, head)}
    store.heads = (head.knowledge_revision.id, None)
    monkeypatch.setattr(store, "get_snapshot", snapshots.get)
    versions = {"v1": SimpleNamespace(content_sha256=first.source_version.content_sha256, status="done"),
                "v2": SimpleNamespace(content_sha256="b" * 64, status="processing")}
    latest = {"id": "v1"}
    monkeypatch.setattr(knowledge.repository, "get_document", lambda _: SimpleNamespace(
        id=first.document_id, workspace_id=first.workspace_id, latest_version_id=latest["id"]))
    monkeypatch.setattr(knowledge.repository, "get_version", lambda _, version_id: versions[version_id])
    path = f"/v1/documents/{first.document_id}/knowledge"
    # Version 2 was parsed (canonical head) but its job is not usable yet: version 1 is served.
    assert client.get(path).json()["latest_revision_id"] == first.knowledge_revision.id
    latest["id"] = "v2"
    assert client.get(path).status_code == 404
    versions["v2"].status = "partial"
    assert client.get(path).json()["latest_revision_id"] == "revision-of-version-2"
