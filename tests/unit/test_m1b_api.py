"""HTTP format dispatch keeps existing registration/upload contracts."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from docgrain_api.main import app
from docgrain_api.routers import documents as routes
from fastapi.testclient import TestClient

client = TestClient(app)


def _register(filename: str, mime_type: str, size: int):
    return client.post("/v1/documents", json={"workspace_id": "m1b-test", "filename": filename,
                                                "mime_type": mime_type, "byte_size": size})


def test_registration_supports_four_formats_and_rejects_mismatch(live_repository) -> None:
    for filename, mime in (("a.pdf", "application/pdf"), ("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                           ("a.txt", "text/plain"), ("a.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")):
        assert _register(filename, mime, 8).status_code == 202
    assert _register("a.docx", "application/pdf", 8).status_code == 415
    # WP106: HTML is a Docling format now; an unknown type is still refused.
    assert _register("a.exe", "application/octet-stream", 8).status_code == 415
    assert _register("a.html", "application/pdf", 8).status_code == 415


def test_upload_rejects_mismatched_and_corrupt_bytes(monkeypatch, live_repository) -> None:
    monkeypatch.setattr(routes, "put_upload", lambda *args: None)
    pdf = _register("a.pdf", "application/pdf", 8).json()
    assert client.put(pdf["upload_url"], files={"file": ("a.pdf", b"not-pdf!", "application/pdf")}).status_code == 415
    docx = _register("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 8).json()
    assert client.put(docx["upload_url"], files={"file": ("a.docx", b"PKbroken", "application/octet-stream")}).status_code == 422


def test_octet_stream_accepts_verified_ooxml(monkeypatch, live_repository) -> None:
    stored = []
    monkeypatch.setattr(routes, "put_upload", lambda *args: stored.append(args))
    data = BytesIO()
    with ZipFile(data, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<document/>")
    content = data.getvalue()
    registration = _register("a.docx", "application/octet-stream", len(content)).json()
    upload = client.put(registration["upload_url"], files={"file": ("a.docx", content, "application/octet-stream")})
    assert upload.status_code == 201
    assert stored[0][-1] == len(content)
