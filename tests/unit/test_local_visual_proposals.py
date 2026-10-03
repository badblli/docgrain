"""Pinned local proposal boundary: storage failures, limits and no cloud fallback."""
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from docgrain_api import local_vision
from docgrain_api.review_publication import StorageIntegrityError
from docgrain_api.routers import local_visuals
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from tests.unit.test_revision_chat import DIGEST, make_snapshot

REAL_GENERATE = local_vision.generate


@pytest.fixture
def env(monkeypatch):
    snapshot = make_snapshot()
    snapshot.source_version.content_sha256 = "c" * 64
    image = BytesIO()
    Image.new("RGB", (100, 80), "white").save(image, "PNG")
    state = SimpleNamespace(snapshot=snapshot, data=image.getvalue(), calls=[], source=[], error=None,
                            settings=SimpleNamespace(use_fixtures=False, docgrain_local_vision_enabled=True,
                                                     docgrain_local_vision_url="http://127.0.0.1:11435",
                                                     docgrain_local_vision_api_key="secret", s3_bucket="b"))
    monkeypatch.setattr(local_visuals, "get_settings", lambda: state.settings)
    monkeypatch.setattr(local_vision, "get_settings", lambda: state.settings)
    monkeypatch.setattr(local_visuals, "get_revision", lambda _: state.snapshot)
    monkeypatch.setattr(local_visuals, "_snapshot_digest", lambda _: DIGEST)
    monkeypatch.setattr(local_visuals, "_fetch_image", lambda *_: state.data)
    monkeypatch.setattr(local_visuals, "storage_client", lambda: object())

    def source(*args):
        state.source.append(True)
        if state.error:
            raise state.error
    monkeypatch.setattr(local_visuals, "verified_source", source)
    monkeypatch.setattr(local_vision, "ready", lambda: True)

    def generate(mime, data):
        state.calls.append((mime, data))
        return local_vision.Observation(classification="unknown", description=None, visible_text=[],
                                       uncertainties=["Yazı okunamıyor"])
    monkeypatch.setattr(local_vision, "generate", generate)
    app = FastAPI()
    app.include_router(local_visuals.router)
    state.client = TestClient(app)
    return state


def propose(env, **changes):
    return env.client.post("/v1/knowledge/revisions/rev1/visuals/local/proposals",
                           json={"snapshot_sha256": DIGEST, "node_id": "img1", **changes})


def test_unreadable_visual_stays_unknown_with_all_source_bindings(env):
    before = vars(env.snapshot).copy()
    result = propose(env)
    assert result.status_code == 200
    data = result.json()
    assert data["description"] is None and data["classification"] == "unknown"
    assert data["review_status"] == "proposed" and data["uncertainties"]
    assert data["node_id"] == "img1" and data["artifact_id"] == "a1"
    assert data["evidence_ids"] == ["e-i1"] and data["source_sha256"] == "c" * 64
    assert data["binary_sha256"] == "b" * 64 and data["snapshot_sha256"] == DIGEST
    assert "model_sha256" in data and "prompt_sha256" in data
    assert env.source == [True] and len(env.calls) == 1
    assert vars(env.snapshot) == before  # read-only boundary
    assert "secret" not in result.text


@pytest.mark.parametrize("changes,code", [({"snapshot_sha256": "d" * 64}, 409),
                                         ({"node_id": "t1"}, 422), ({"node_id": "img2"}, 422),
                                         ({"node_id": "missing"}, 422), ({"node_id": "img-bare"}, 422),
                                         ({"extra": 1}, 422)])
def test_stale_foreign_unbound_or_invalid_fields_never_call_model(env, changes, code):
    assert propose(env, **changes).status_code == code
    assert not env.calls and not env.source


def test_demo_and_disabled_have_no_model_or_storage_calls(env):
    env.settings.use_fixtures = True
    assert propose(env).status_code == 409
    assert not env.client.get("/v1/knowledge/revisions/rev1/visuals/local/config").json()["enabled"]
    env.settings.use_fixtures = False
    env.settings.docgrain_local_vision_enabled = False
    assert propose(env).status_code == 503 and not env.calls and not env.source


def test_corrupt_source_and_invalid_image_release_lock(env):
    env.error = StorageIntegrityError("secret/provider detail")
    response = propose(env)
    assert response.status_code == 409 and "secret" not in response.text
    assert not env.calls
    env.error = None
    env.data = b"not a PNG"
    assert propose(env).status_code == 422 and not env.calls
    assert local_vision.INFERENCE_LOCK.acquire(blocking=False)
    local_vision.INFERENCE_LOCK.release()


def test_bound_bytes_and_pixel_caps_are_enforced_before_inference(env, monkeypatch):
    env.snapshot.artifacts[0].byte_size = local_visuals.MAX_IMAGE_BYTES + 1
    assert propose(env).status_code == 413 and not env.source
    env.snapshot.artifacts[0].byte_size = 10
    monkeypatch.setattr(local_visuals, "MAX_IMAGE_PIXELS", 10)
    assert propose(env).status_code == 422 and not env.calls


def test_concurrent_selected_requests_are_bounded(env):
    local_vision.INFERENCE_LOCK.acquire()
    try:
        assert propose(env).status_code == 429
        assert not env.calls and not env.source
    finally:
        local_vision.INFERENCE_LOCK.release()


@pytest.mark.parametrize("error,code", [(local_vision.LocalUnavailable, 503), (local_vision.LocalMalformed, 502)])
def test_model_failure_is_not_accepted_and_releases_lock(env, monkeypatch, error, code):
    def fail(*_):
        raise error()
    monkeypatch.setattr(local_vision, "generate", fail)
    assert propose(env).status_code == code
    assert local_vision.INFERENCE_LOCK.acquire(blocking=False)
    local_vision.INFERENCE_LOCK.release()


@pytest.mark.parametrize("url", ["https://cloud.example:11435", "http://example.com:11435",
                                 "http://127.0.0.1:11435/path", "http://u:p@localhost:11435",
                                 "http://localhost:11435?key=1", "http://localhost:11436"])
def test_transport_cannot_route_documents_to_remote_or_arbitrary_endpoint(env, url):
    env.settings.docgrain_local_vision_url = url
    with pytest.raises(local_vision.LocalUnavailable):
        local_vision._endpoint()


@pytest.mark.parametrize("change", [{"description": " "}, {"uncertainties": ["x" * 501]},
                                    {"classification": "certified"}, {"extra": True}])
def test_malformed_semantic_claim_envelope_fails_closed(change):
    with pytest.raises(ValueError):
        local_vision.Observation.model_validate({"classification": "plan", "description": None,
                                               "visible_text": [], "uncertainties": [], **change})


def test_truncated_or_wrong_model_response_is_rejected(env, monkeypatch):
    # Restore the real generator; its bounded transport is isolated here.
    generate = REAL_GENERATE
    monkeypatch.setattr(local_vision, "ready", lambda: True)
    raw = {"model": local_vision.PROFILE_ID, "choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
    monkeypatch.setattr(local_vision, "_request", lambda *_: raw)
    with pytest.raises(local_vision.LocalMalformed):
        generate("image/png", env.data)
    raw["choices"][0]["finish_reason"] = "stop"
    raw["model"] = "wrong"
    raw["choices"][0]["message"]["content"] = json.dumps({"classification": "unknown", "description": None,
                                                        "visible_text": [], "uncertainties": []})
    with pytest.raises(local_vision.LocalMalformed):
        generate("image/png", env.data)
