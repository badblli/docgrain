"""Contract smoke tests.

These guard the two things a consumer actually depends on: the shape of a
chunk, and the legality of job transitions. Run with `pytest` from the repo
root once `apps/api` and `packages/domain` are installed.
"""

from __future__ import annotations

import pytest
from docgrain_api.main import app
from docgrain_api.routers import documents as document_routes
from docgrain_domain import JobStage, JobStatus, StageStatus
from docgrain_domain.state import (
    JobStateError,
    assert_transition,
    next_stage,
    resolve_job_status,
    retryable_stages,
)
from fastapi.testclient import TestClient

client = TestClient(app)

REQUIRED_CHUNK_FIELDS = {
    "id",
    "document_id",
    "document_version_id",
    "workspace_id",
    "text",
    "embedding_text",
    "heading_path",
    "page_numbers",
    "source_uri",
    "page_image_uris",
    "asset_ids",
    "table_ids",
    "access_scope",
}


def test_healthz() -> None:
    assert client.get("/healthz").status_code == 200


def test_registered_file_can_be_stored_then_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[str, object] = {}

    def fake_put(object_name: str, data: object, content_type: str, length: int) -> None:
        stored.update(object_name=object_name, content_type=content_type, length=length)

    monkeypatch.setattr(document_routes, "put_upload", fake_put)
    monkeypatch.setattr(document_routes, "object_exists", lambda object_name: object_name == stored["object_name"])

    registration = client.post(
        "/v1/documents",
        json={
            "workspace_id": "ws_luwi",
            "filename": "test.txt",
            "mime_type": "text/plain",
            "byte_size": 4,
        },
    )
    assert registration.status_code == 202
    payload = registration.json()
    upload = client.put(
        payload["upload_url"],
        files={"file": ("test.txt", b"test", "text/plain")},
    )
    assert upload.status_code == 201
    assert stored["length"] == 4
    confirmation = client.post(
        f"/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/uploaded"
    )
    assert confirmation.status_code == 202
    assert confirmation.json()["job_id"] == payload["job_id"]


def test_canonical_markdown_artifact_stays_behind_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_routes, "get_text", lambda _: "# Canonical output")
    response = client.get("/v1/documents/doc_7fk2/versions/dver_2/artifacts/document.md")
    assert response.status_code == 200
    assert response.text == "# Canonical output"


def test_every_chunk_carries_the_contract_fields() -> None:
    chunks = client.get("/v1/versions/dver_2/chunks").json()
    assert chunks
    for chunk in chunks:
        assert REQUIRED_CHUNK_FIELDS <= set(chunk)
        assert chunk["page_numbers"] or chunk["asset_ids"] or chunk["table_ids"]
        assert chunk["heading_path"][0] in chunk["embedding_text"]


def test_page_resolves_its_own_provenance() -> None:
    page = client.get("/v1/versions/dver_2/pages/4").json()
    assert "tbl_01" in page["table_ids"]
    assert page["chunk_ids"]


def test_neighbors_are_sorted_and_exclude_self() -> None:
    neighbors = client.get("/v1/chunks/chk_06/neighbors").json()
    assert all(n["chunk_id"] != "chk_06" for n in neighbors)
    assert neighbors == sorted(neighbors, key=lambda n: n["score"], reverse=True)


def test_cosine_is_stable_across_calls() -> None:
    first = client.get("/v1/chunks/chk_06/neighbors").json()
    second = client.get("/v1/chunks/chk_06/neighbors").json()
    assert first == second


def test_boundaries_flag_low_similarity_pairs() -> None:
    report = client.get("/v1/versions/dver_2/chunks/boundaries").json()
    assert report["points"]
    for point in report["points"]:
        assert point["is_boundary"] is (point["score"] < report["threshold"])


def test_stage_order_is_the_documented_ten() -> None:
    assert next_stage(JobStage.REGISTER) is JobStage.RENDER
    assert next_stage(JobStage.PUBLISH) is None


def test_terminal_states_are_terminal() -> None:
    with pytest.raises(JobStateError):
        assert_transition(JobStatus.DONE, JobStatus.RUNNING)


def test_page_failures_make_a_job_partial_not_done() -> None:
    all_done = dict.fromkeys(JobStage, StageStatus.DONE)
    assert resolve_job_status(all_done, has_page_failures=False) is JobStatus.DONE
    assert resolve_job_status(all_done, has_page_failures=True) is JobStatus.PARTIAL


def test_retry_replays_the_failed_stage_and_everything_after() -> None:
    statuses = dict.fromkeys(JobStage, StageStatus.DONE)
    statuses[JobStage.VISION] = StageStatus.FAILED
    replays = retryable_stages(statuses)
    assert replays[0] is JobStage.VISION
    assert JobStage.PUBLISH in replays
