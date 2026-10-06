"""Opt-in end-to-end API/PostgreSQL/MinIO/worker check using synthetic TXT."""

import os
from uuid import uuid4

import httpx
import pytest
from docgrain_ingest.cli import ingest_folder


@pytest.mark.skipif(not os.getenv("DOCGRAIN_BUNDLE_API_URL"), reason="requires explicit live API URL")
def test_company_bundle_live_api(tmp_path):
    workspace = f"ws_bundle_test_{uuid4().hex}"
    folder = tmp_path / "company"
    folder.mkdir()
    (folder / "guide.txt").write_text("Standard room capacity is two people.\n", encoding="utf-8")
    (folder / "renamed.txt").write_bytes((folder / "guide.txt").read_bytes())
    with httpx.Client(base_url=os.environ["DOCGRAIN_BUNDLE_API_URL"], timeout=60) as client:
        first = ingest_folder(folder, workspace, client, report_path=tmp_path / "bundle.json")
        second = ingest_folder(folder, workspace, client, report_path=tmp_path / "bundle.json")
        assert all(row["status"] == "done" and row["pages"] >= 1 for row in first["files"])
        assert all(not row["issues"] for row in first["files"])
        assert all(row["reused"] for row in second["files"])
        ids = {row["document_id"] for row in first["files"]}
        assert len(ids) == 1
        assert {row["document_id"] for row in second["files"]} == ids
        response = client.get("/v1/documents", params={"workspace_id": workspace})
        response.raise_for_status()
        listed = response.json()
        assert len(listed) == 1
        assert listed[0]["document"]["workspace_id"] == workspace
        version = listed[0]["latest_version"]
        assert f"/uploads/{workspace}/" in version["source_uri"]
        assert version["page_count"] >= 1
