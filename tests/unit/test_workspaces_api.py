"""Tests for GET /v1/workspaces listing."""

from datetime import UTC, datetime

from docgrain_api.main import app
from docgrain_domain import Document
from fastapi.testclient import TestClient

client = TestClient(app)


def test_workspaces_fixture_mode():
    response = client.get("/v1/workspaces")
    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) >= 1
    assert any(ws["id"] == "ws_demo" for ws in workspaces)
    assert all("id" in ws and "documents" in ws for ws in workspaces)


def test_workspaces_live_mode_empty(live_repository):
    response = client.get("/v1/workspaces")
    assert response.status_code == 200
    assert response.json() == []


def test_workspaces_live_mode_counts_and_order(live_repository):
    doc1 = Document(
        id="doc_1",
        workspace_id="ws_first",
        title="First",
        filename="first.pdf",
        mime_type="application/pdf",
        latest_version_id="v1",
        version_count=1,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    doc2 = Document(
        id="doc_2",
        workspace_id="ws_second",
        title="Second",
        filename="second.pdf",
        mime_type="application/pdf",
        latest_version_id="v1",
        version_count=1,
        created_at=datetime(2025, 2, 1, tzinfo=UTC),
        updated_at=datetime(2025, 2, 1, tzinfo=UTC),
    )
    doc3 = Document(
        id="doc_3",
        workspace_id="ws_first",
        title="Third",
        filename="third.pdf",
        mime_type="application/pdf",
        latest_version_id="v1",
        version_count=1,
        created_at=datetime(2025, 3, 1, tzinfo=UTC),
        updated_at=datetime(2025, 3, 1, tzinfo=UTC),
    )
    live_repository["documents"]["doc_1"] = doc1
    live_repository["documents"]["doc_2"] = doc2
    live_repository["documents"]["doc_3"] = doc3

    response = client.get("/v1/workspaces")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    # ws_first has latest updated_at (2025-03-01)
    assert items[0]["id"] == "ws_first"
    assert items[0]["documents"] == 2
    assert items[1]["id"] == "ws_second"
    assert items[1]["documents"] == 1
