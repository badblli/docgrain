"""Revision chat API: every provider and storage call is mocked; no network is used."""

from types import SimpleNamespace

import pytest
from docgrain_api.routers import chat
from docgrain_domain.canonical.models import Evidence
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

DIGEST = "a" * 64
SECRET = "super-secret-key"
PNG = b"\x89PNG-bytes"


def ann(ids=(), status="approved", method="manual"):
    return SimpleNamespace(review_status=status, provenance=SimpleNamespace(
        method=method, derivation="direct", evidence_ids=list(ids)))


def node(node_id, kind, evidence=(), status="approved", **extra):
    return SimpleNamespace(id=node_id, kind=kind, annotation=ann(evidence, status), field_annotations={}, **extra)


def evidence(evidence_id):
    return Evidence(id=evidence_id, source_version_id="sv", locator={"kind": "text_span", "start": 0, "end": 5})


def artifact(artifact_id, mime="image/png", size=None, role="source-image"):
    return SimpleNamespace(id=artifact_id, role=role, mime_type=mime, byte_size=len(PNG) if size is None else size, content_sha256="b" * 64,
                           storage_uri="s3://b/x?versionId=1")


def make_snapshot(**overrides):
    cell = SimpleNamespace(value=7, display_text=None, formula=None, cached_value=None, annotation=ann(["e-cell"]))
    structure = [
        node("doc", "document", children=["t1", "tbl", "img1", "img2", "img3", "img-bare"], title="Doc"),
        node("t1", "text_block", ["e1"], text="Toplam 7 TL", role="paragraph"),
        node("tbl", "table", ["e-tbl"], rows=[[cell]], caption=None),
        node("img1", "asset", ["e-i1"], artifact_id="a1", description="Bir grafik", status="proposed"),
        node("img2", "asset", [], artifact_id="a2", description=None),
        node("img3", "asset", [], artifact_id="a3", description=None),
        node("img-bare", "asset", [], artifact_id="a-pdf", description="Açıklamalı ama PDF", ),
    ]
    values = {
        "document_id": "doc-1", "workspace_id": "ws",
        "source_version": SimpleNamespace(id="sv", storage_uri="s3://b/uploads/doc-1/v/original"),
        "knowledge_revision": SimpleNamespace(id="rev1", coverage="complete"),
        "root_node_id": "doc", "structure": structure,
        "evidence": [evidence(e) for e in ("e1", "e-cell", "e-tbl", "e-i1", "e-other")],
        "artifacts": [artifact("a1"), artifact("a2"), artifact("a3", "image/jpeg"), artifact("a-pdf", "application/pdf")],
        "metadata": {"structural_parse": {"issues": [{"code": "ocr_needs_review", "reason": "OCR"}]}},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def env(monkeypatch):
    state = SimpleNamespace(snapshot=make_snapshot(), generate=[], fetch=[], reply=None, error=None,
                            settings=SimpleNamespace(use_fixtures=False, gemini_chat_enabled=True, gemini_api_key=SECRET,
                                                     gemini_model="gemini-test", s3_bucket="b"))

    def get_revision(revision_id):
        if revision_id != "rev1":
            raise HTTPException(404, "canonical revision not found")
        return state.snapshot

    def generate(**kwargs):
        state.generate.append(kwargs)
        if state.error:
            raise state.error
        return state.reply

    def fetch(snapshot, art):
        state.fetch.append(art.id)
        return PNG

    monkeypatch.setattr(chat, "get_settings", lambda: state.settings)
    monkeypatch.setattr(chat, "get_revision", get_revision)
    monkeypatch.setattr(chat, "_snapshot_digest", lambda snapshot: DIGEST)
    monkeypatch.setattr(chat, "_generate", generate)
    monkeypatch.setattr(chat, "_fetch_image", fetch)
    app = FastAPI()
    app.include_router(chat.router)
    state.client = TestClient(app)
    state.reply = {"answer": "Toplam 7 TL.", "abstained": False,
                   "citations": [{"node_id": "t1", "evidence_id": "e1"}], "image_node_ids": []}
    return state


def ask(env, revision="rev1", **overrides):
    body = {"snapshot_sha256": DIGEST, "question": "Toplam nedir?", "allow_remote": True, "image_node_ids": []}
    body.update(overrides)
    return env.client.post(f"/v1/knowledge/revisions/{revision}/chat", json=body)


def test_config_reports_only_safe_flags(env):
    response = env.client.get("/v1/knowledge/revisions/rev1/chat/config")
    assert response.json() == {"enabled": True, "model": "gemini-test"}
    env.settings.gemini_api_key = ""
    assert env.client.get("/v1/knowledge/revisions/rev1/chat/config").json()["enabled"] is False
    env.settings.gemini_api_key, env.settings.gemini_chat_enabled = SECRET, False
    assert env.client.get("/v1/knowledge/revisions/rev1/chat/config").json()["enabled"] is False
    assert SECRET not in env.client.get("/v1/knowledge/revisions/rev1/chat/config").text


def test_demo_is_409_and_disabled_or_missing_key_is_503(env):
    env.settings.use_fixtures = True
    assert ask(env).status_code == 409
    env.settings.use_fixtures = False
    env.settings.gemini_chat_enabled = False
    assert ask(env).status_code == 503
    env.settings.gemini_chat_enabled, env.settings.gemini_api_key = True, "  "
    assert ask(env).status_code == 503
    assert env.generate == [] and env.fetch == []


@pytest.mark.parametrize("override", [
    {"allow_remote": False}, {"allow_remote": 1}, {"allow_remote": "true"}, {"question": "   "},
    {"question": "x" * 2001}, {"snapshot_sha256": "A" * 64}, {"snapshot_sha256": "a" * 63},
    {"image_node_ids": ["img1", "img2", "img3", "t1"]}, {"image_node_ids": [""]}, {"extra": 1},
])
def test_request_is_strict(env, override):
    assert ask(env, **override).status_code == 422
    assert env.generate == []


def test_missing_flag_is_422(env):
    body = {"snapshot_sha256": DIGEST, "question": "q", "image_node_ids": []}
    assert env.client.post("/v1/knowledge/revisions/rev1/chat", json=body).status_code == 422


def test_unknown_revision_404_and_pin_mismatch_409(env):
    assert ask(env, revision="other").status_code == 404
    assert ask(env, snapshot_sha256="c" * 64).status_code == 409
    assert env.generate == [] and env.fetch == []


@pytest.mark.parametrize("ids", [["img1", "img1"], ["ghost"], ["t1"], ["img-bare"]])
def test_bad_image_ids_are_422_without_fetch(env, ids):
    assert ask(env, image_node_ids=ids).status_code == 422
    assert env.fetch == [] and env.generate == []


def test_oversized_context_is_413_and_never_truncated(env):
    env.snapshot.structure[1].text = "x" * chat.MAX_CONTEXT_CHARS
    response = ask(env, image_node_ids=["img1"])
    assert response.status_code == 413
    assert env.fetch == [] and env.generate == []


def test_image_budget_is_413_before_fetch(env):
    env.snapshot.artifacts[0].byte_size = chat.MAX_IMAGE_TOTAL_BYTES + 1
    assert ask(env, image_node_ids=["img1"]).status_code == 413
    assert env.fetch == []


def test_text_only_answer_sends_context_not_images(env):
    response = ask(env)
    assert response.status_code == 200
    body = response.json()
    assert body["revision_id"] == "rev1" and body["snapshot_sha256"] == DIGEST and body["model"] == "gemini-test"
    assert body["citations"][0]["node_id"] == "t1" and body["citations"][0]["evidence"]["id"] == "e1"
    assert body["images"] == [] and not body["abstained"]
    assert any("model yorumudur" in warning for warning in body["warnings"])
    assert any("kayıtlı eksik" in warning for warning in body["warnings"])
    call = env.generate[0]
    assert call["images"] == [] and env.fetch == []
    assert "Toplam 7 TL" in call["text"] and "Toplam nedir?" in call["text"]
    assert "storage_uri" not in call["text"] and "s3://" not in call["text"]
    assert SECRET not in response.text


def test_cell_evidence_can_be_cited(env):
    env.reply["citations"] = [{"node_id": "tbl", "evidence_id": "e-cell"}]
    assert ask(env).status_code == 200


def test_selected_image_bytes_are_fetched_and_server_builds_the_image(env):
    env.snapshot.structure[4].annotation = ann(["e-i2"])
    env.snapshot.evidence.append(evidence("e-i2"))
    env.reply.update(image_node_ids=["img2"], citations=[{"node_id": "img2", "evidence_id": "e-i2"}])
    response = ask(env, image_node_ids=["img2", "img1"])
    assert response.status_code == 200
    assert env.fetch == ["a2", "a1"]
    assert env.generate[0]["images"] == [("image/png", PNG), ("image/png", PNG)]
    image = response.json()["images"][0]
    assert image == {"node_id": "img2", "caption": None, "description": None,
                     "artifact_url": "/v1/knowledge/revisions/rev1/artifacts/a2", "evidence_ids": ["e-i2"]}
    assert any("Gönderilen görsellerin" in warning for warning in response.json()["warnings"])


def test_described_unselected_image_may_be_returned_with_unaccepted_warning(env):
    env.reply["image_node_ids"] = ["img1"]
    env.reply["citations"] = [{"node_id": "img1", "evidence_id": "e-i1"}]
    response = ask(env)
    assert response.status_code == 200
    assert response.json()["images"][0]["evidence_ids"] == ["e-i1"]
    assert env.fetch == []


def test_abstaining_needs_no_citation_but_is_still_warned(env):
    env.reply = {"answer": "Belgede yeterli bilgi yok.", "abstained": True, "citations": [], "image_node_ids": []}
    response = ask(env)
    assert response.status_code == 200 and response.json()["abstained"] is True
    assert response.json()["warnings"]


def test_described_image_requires_its_own_source_citation(env):
    env.reply["image_node_ids"] = ["img1"]
    # A valid unrelated text citation cannot certify the returned image.
    assert ask(env).status_code == 502


@pytest.mark.parametrize("bad", [
    {"citations": [{"node_id": "ghost", "evidence_id": "e1"}]},
    {"citations": [{"node_id": "t1", "evidence_id": "e-other"}]},
    {"citations": [{"node_id": "t1", "evidence_id": "missing"}]},
    {"citations": [{"node_id": "t1", "evidence_id": "e-cell"}]},
    {"citations": []},
    {"image_node_ids": ["img2"]},
    {"image_node_ids": ["ghost"]},
    {"image_node_ids": ["t1"]},
    {"image_node_ids": ["img-bare"]},
    {"image_node_ids": ["img1", "img1"]},
    {"image_node_ids": ["img1", "img2", "img3", "img1"]},
    {"answer": "x" * 12001},
    {"answer": ""},
    {"abstained": "false"},
    {"extra": 1},
])
def test_unvalidated_model_output_is_generic_502(env, bad):
    env.reply = {**env.reply, **bad}
    response = ask(env)
    assert response.status_code == 502
    assert response.json() == {"detail": "Model yanıtı doğrulanamadı."}


@pytest.mark.parametrize("raw", [None, [], "text", {"answer": "x"}])
def test_non_object_or_incomplete_output_is_502(env, raw):
    env.reply = raw
    assert ask(env).status_code == 502


def test_provider_failure_is_generic_503_without_secret(env):
    env.error = chat.ProviderUnavailable()
    response = ask(env)
    assert response.status_code == 503 and SECRET not in response.text
    env.error = chat.ProviderMalformed()
    assert ask(env).status_code == 502


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit):
        return self.payload[:limit]


def _patch_opener(monkeypatch, payload=None, error=None):
    seen = {}

    class Opener:
        def open(self, request, timeout):
            seen.update(request=request, timeout=timeout)
            if error:
                raise error
            return _Response(payload)

    monkeypatch.setattr(chat.urllib.request, "build_opener", lambda *handlers: Opener())
    return seen


def _envelope(text):
    import json
    return json.dumps({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}).encode()


def test_generate_request_shape_has_key_only_in_header(monkeypatch):
    seen = _patch_opener(monkeypatch, _envelope('{"answer": "ok"}'))
    result = chat._generate(model="gemini-test", api_key=SECRET, text="{}", images=[("image/png", PNG)])
    request = seen["request"]
    assert result == {"answer": "ok"} and seen["timeout"] == 45
    assert request.full_url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert request.get_method() == "POST" and request.get_header("X-goog-api-key") == SECRET
    assert SECRET not in request.full_url
    import json
    body = json.loads(request.data)
    assert body["generationConfig"]["temperature"] == 0
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in body["generationConfig"] and "tools" not in body
    assert body["contents"][0]["role"] == "user"
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": "{}"} and parts[1]["inlineData"]["mimeType"] == "image/png"
    assert "untrusted" in body["systemInstruction"]["parts"][0]["text"]


def test_generate_maps_transport_errors_without_detail(monkeypatch):
    import urllib.error
    _patch_opener(monkeypatch, error=urllib.error.URLError(f"boom {SECRET}"))
    with pytest.raises(chat.ProviderUnavailable) as caught:
        chat._generate(model="gemini-test", api_key=SECRET, text="{}", images=[])
    assert SECRET not in str(caught.value) and caught.value.__cause__ is None
    with pytest.raises(chat.ProviderUnavailable):
        chat._generate(model="bad/model?key=x", api_key=SECRET, text="{}", images=[])


@pytest.mark.parametrize("payload", [
    b"not json", b"{}", _envelope("not json"), b"x" * (chat.MAX_RESPONSE_BYTES + 1),
    b'{"candidates":[{"finishReason":"SAFETY","content":{"parts":[{"text":"{}"}]}}]}',
], ids=lambda raw: f"payload-{len(raw)}")
def test_generate_rejects_malformed_or_oversized_envelopes(monkeypatch, payload):
    _patch_opener(monkeypatch, payload)
    with pytest.raises(chat.ProviderMalformed):
        chat._generate(model="gemini-test", api_key=SECRET, text="{}", images=[])







def test_config_validates_revision_scope(env):
    assert env.client.get("/v1/knowledge/revisions/foreign/chat/config").status_code == 404


def test_real_canonical_context_digest_and_cell_types():
    from docgrain_domain.canonical.lifecycle import digest

    from tests.unit.test_manual_review import modern
    snapshot = modern()
    assert chat._snapshot_digest(snapshot) == digest(snapshot.model_dump(mode="json"))
    context, _gaps = chat._build_context(snapshot)
    assert context["revision_id"] == snapshot.knowledge_revision.id
    assert all(item["id"] in {n.id for n in snapshot.structure} for item in context["nodes"])
    cell = SimpleNamespace(value=1.5, display_text="1,50 TL", cached_value=None, formula=None, annotation=None)
    entry = chat._cell_entry(cell)
    assert entry["v"] == 1.5 and entry["display_text"] == "1,50 TL"
    assert "storage_uri" not in chat._dumps(context)
