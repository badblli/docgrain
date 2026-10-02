"""Local OCR output validation, structured failures and proposal validation."""

import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from docgrain_domain.canonical.visuals import visual_inventory
from docgrain_worker import local_visual_ocr
from docgrain_worker.local_visual_ocr import (
    LocalOCRSession,
    validate_local_ocr_proposal,
)
from tests.unit.test_n3_visuals import visual_snapshot as fixture

PROFILE = {"review_threshold": 0.8, "device": "cpu", "download_enabled": False}
NAN = float("nan")
INF = float("inf")


def box(x0=10, y0=10, x1=50, y1=30):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


GOOD = (box(), "Izmir 127", 0.9)


def setup(monkeypatch, outputs, **fixture_args):
    """Session whose reader returns (or raises) each queued output in turn."""
    snapshot, source, image = fixture(**fixture_args)
    inventory = visual_inventory(snapshot)
    assets = [r for r in inventory.regions if r.node_kind == "asset"]
    calls = []
    queue = list(outputs)

    def readtext(_prepared, **options):
        calls.append(options)
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    session = LocalOCRSession()
    session._reader = SimpleNamespace(readtext=readtext)
    session._profile = PROFILE
    monkeypatch.setattr(local_visual_ocr, "verified_profile", lambda: PROFILE)
    return session, snapshot, inventory, assets, source, image, calls


@pytest.mark.parametrize(
    "bad",
    [
        [([[0, 0], [1, 1], [2, 2]], "x", 0.9)],  # three points
        [([[0, 0, 0]] * 4, "x", 0.9)],  # three coordinates
        [("polygon", "x", 0.9)],
        [(box(NAN, 10, 50, 30), "x", 0.9)],
        [(box(10, 10, INF, 30), "x", 0.9)],
        [(GOOD[0], "x", NAN)],
        [(GOOD[0], "x", INF)],
        [(GOOD[0], "x", 1.5)],
        [(GOOD[0], "x", "0.9")],
        [(GOOD[0], "x", True)],
        [(box(10, 10, 500, 30), "x", 0.9)],  # outside the 100x60 frame
        [(box(-20, 10, 50, 30), "x", 0.9)],
        [(box(10, 10, 10, 30), "x", 0.9)],  # zero width
        [(box(10, 10, 50, 10), "x", 0.9)],  # zero height
        [(GOOD[0], b"bytes", 0.9)],
        [(GOOD[0], "x")],
        ["not a row"],
        [GOOD, ([], "x", 0.9)],  # one valid row never rescues an invalid one
        "not a list",
        None,
    ],
)
def test_invalid_recognizer_output_is_not_cached_and_retry_calls_reader_again(
    bad, monkeypatch
):
    session, snapshot, inventory, assets, source, image, calls = setup(
        monkeypatch, [bad, [GOOD]]
    )
    failed = session.extract(snapshot, inventory, assets[0].id, source, image)
    assert failed["execution_status"] == "failed"
    assert failed["failure"] == "invalid_recognizer_output"
    assert failed["words"] == [] and failed["visible_text"] == []
    assert failed["observation_sha256"] is None and failed["cache_hit"] is False
    assert set(failed["timings_s"]) == {"reader_load", "ocr", "total"}
    assert not session._cache
    validate_local_ocr_proposal(snapshot, inventory, failed, source, image)
    retry = session.extract(snapshot, inventory, assets[0].id, source, image)
    assert retry["execution_status"] == "done" and not retry["cache_hit"]
    assert retry["visible_text"] == ["Izmir 127"] and len(calls) == 2
    assert len(session._cache) == 1


def test_numpy_scalar_coordinates_are_accepted(monkeypatch):
    np = pytest.importorskip("numpy")
    row = (
        [[np.float32(10), np.int64(10)], [np.float64(50), np.float32(10)]]
        + [[np.int32(50), np.float64(30)], [np.float32(10), np.int64(30)]],
        "numpy",
        np.float32(0.5),
    )
    session, snapshot, inventory, assets, source, image, _ = setup(monkeypatch, [[row]])
    result = session.extract(snapshot, inventory, assets[0].id, source, image)
    assert result["execution_status"] == "done"
    assert result["visible_text"] == ["numpy"]
    json.dumps(result)  # plain Python numbers only
    validate_local_ocr_proposal(snapshot, inventory, result, source, image)


def test_recognizer_failure_is_explicit_without_exception_text(monkeypatch):
    session, snapshot, inventory, assets, source, image, calls = setup(
        monkeypatch, [RuntimeError("secret C:\\models\\path"), [GOOD]]
    )
    failed = session.extract(snapshot, inventory, assets[0].id, source, image)
    assert failed["execution_status"] == "failed"
    assert failed["failure"] == "recognizer_failed"
    assert failed["uncertainties"] == ["local_ocr_failed"]
    assert failed["words"] == [] and failed["visible_text"] == []
    assert failed["observation_sha256"] is None
    assert "secret" not in json.dumps(failed) and not session._cache
    validate_local_ocr_proposal(snapshot, inventory, failed, source, image)
    assert (
        session.extract(snapshot, inventory, assets[0].id, source, image)[
            "execution_status"
        ]
        == "done"
    )
    assert len(calls) == 2


def test_reader_initialization_failure_is_structured_after_profile_verified(
    monkeypatch,
):
    session, snapshot, inventory, assets, source, image, _ = setup(monkeypatch, [])
    session._reader = None
    session._profile = None

    class Reader:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("secret weights location")

    monkeypatch.setitem(sys.modules, "easyocr", SimpleNamespace(Reader=Reader))
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _n: None)
    )
    monkeypatch.setattr("docgrain_worker.ocr.model_directory", lambda: "models")
    failed = session.extract(snapshot, inventory, assets[0].id, source, image)
    assert failed["execution_status"] == "failed"
    assert failed["failure"] == "reader_initialization_failed"
    assert failed["words"] == [] and failed["observation_sha256"] is None
    assert set(failed["timings_s"]) == {"reader_load", "ocr", "total"}
    assert "secret" not in json.dumps(failed) and not session._cache
    validate_local_ocr_proposal(snapshot, inventory, failed, source, image)


def test_unverified_profile_fails_closed(monkeypatch):
    session, snapshot, inventory, assets, source, image, _ = setup(monkeypatch, [])
    session._reader = None
    session._profile = None

    def unverified():
        raise RuntimeError("profile not verified")

    monkeypatch.setattr(local_visual_ocr, "verified_profile", unverified)
    with pytest.raises(RuntimeError, match="not verified"):
        session.extract(snapshot, inventory, assets[0].id, source, image)
    assert session._profile is None


def test_failed_proposal_cannot_carry_observations_or_lack_failure_info(monkeypatch):
    session, snapshot, inventory, assets, source, image, _ = setup(
        monkeypatch, [[GOOD], RuntimeError("boom")]
    )
    done = session.extract(snapshot, inventory, assets[0].id, source, image)
    session._cache.clear()
    failed = session.extract(snapshot, inventory, assets[0].id, source, image)
    validate_local_ocr_proposal(snapshot, inventory, failed, source, image)

    def mutate(**changes):
        value = deepcopy(failed)
        value.update(changes)
        with pytest.raises(ValueError):
            validate_local_ocr_proposal(snapshot, inventory, value, source, image)

    mutate(words=deepcopy(done["words"]))
    mutate(words=deepcopy(done["words"]), visible_text=done["visible_text"])
    mutate(visible_text=["invented"])
    mutate(observation_sha256=done["observation_sha256"])
    mutate(failure=None)
    mutate(failure="arbitrary exception text")
    mutate(uncertainties=["visual_meaning_unresolved"])
    mutate(uncertainties="local_ocr_failed")
    mutate(uncertainties=["local_ocr_failed", {}])
    mutate(failure={})
    mutate(execution_status="running")
    mutate(execution_status=None)
    mutate(execution_status=[])
    # A done proposal must not smuggle in a failure.
    value = deepcopy(done)
    value["failure"] = "recognizer_failed"
    with pytest.raises(ValueError):
        validate_local_ocr_proposal(snapshot, inventory, value, source, image)


def test_malformed_request_shape_and_profile_mismatch_are_rejected(monkeypatch):
    session, snapshot, inventory, assets, source, image, _ = setup(
        monkeypatch, [[GOOD]]
    )
    done = session.extract(snapshot, inventory, assets[0].id, source, image)
    validate_local_ocr_proposal(snapshot, inventory, done, source, image)

    def reject(value):
        with pytest.raises(ValueError):
            validate_local_ocr_proposal(snapshot, inventory, value, source, image)

    reject(None)
    reject([])
    reject("proposal")
    reject({})
    for key in ("request", "format", "version"):
        value = deepcopy(done)
        del value[key]
        reject(value)
    for request in (None, "request", [], {}, {"region_id": 7}, {"region_id": None}):
        value = deepcopy(done)
        value["request"] = request
        reject(value)
    value = deepcopy(done)
    value["request"]["region_id"] = "unknown-region"
    reject(value)
    value = deepcopy(done)
    value["format"] = "other"
    reject(value)
    value = deepcopy(done)
    value["execution_status"] = "partial"
    reject(value)
    # Producer differs from the currently verified profile.
    monkeypatch.setattr(
        local_visual_ocr,
        "verified_profile",
        lambda: {**PROFILE, "review_threshold": 0.1},
    )
    with pytest.raises(ValueError, match="processing profile"):
        validate_local_ocr_proposal(snapshot, inventory, done, source, image)


def test_cached_repeated_binary_rebinds_each_region_after_earlier_failure(monkeypatch):
    session, snapshot, inventory, assets, source, image, calls = setup(
        monkeypatch, [[(box(), "bad", NAN)], [GOOD]], orientation=6
    )
    failed = session.extract(snapshot, inventory, assets[0].id, source, image)
    assert failed["execution_status"] == "failed" and not session._cache
    first = session.extract(snapshot, inventory, assets[0].id, source, image)
    second = session.extract(snapshot, inventory, assets[1].id, source, image)
    assert len(calls) == 2 and not first["cache_hit"] and second["cache_hit"]
    assert first["request"]["target_node_id"] == assets[0].node_id
    assert second["request"]["target_node_id"] == assets[1].node_id
    assert first["words"] == second["words"]
    assert first["observation_sha256"] == second["observation_sha256"]
    locator = second["words"][0]["locator"]
    assert (locator["width_px"], locator["height_px"], locator["exif_orientation"]) == (
        100,
        60,
        6,
    )
    validate_local_ocr_proposal(snapshot, inventory, first, source, image)
    validate_local_ocr_proposal(snapshot, inventory, second, source, image)
    # Cached facts are not shared by reference with returned proposals.
    second["words"][0]["text"] = "changed"
    assert session.extract(snapshot, inventory, assets[1].id, source, image)[
        "visible_text"
    ] == ["Izmir 127"]
