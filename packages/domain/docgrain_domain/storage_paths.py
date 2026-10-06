"""Workspace-scoped uploads, with read compatibility for older source receipts."""

from urllib.parse import quote, urlparse


def upload_key(workspace_id: str, document_id: str, version_id: str) -> str:
    return f"uploads/{quote(workspace_id, safe='')}/{document_id}/{version_id}/original"


def source_version_id(uri: str, workspace_id: str, document_id: str) -> str | None:
    parts = urlparse(uri).path.lstrip("/").split("/")
    if len(parts) == 4 and parts[:2] == ["uploads", document_id] and parts[-1] == "original":
        return parts[-2]
    if (len(parts) == 5 and parts[:3] == ["uploads", quote(workspace_id, safe=''), document_id]
            and parts[-1] == "original"):
        return parts[-2]
    return None
