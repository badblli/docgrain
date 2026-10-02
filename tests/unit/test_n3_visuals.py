"""Source binding, unresolved facts, pure previews and selected OCR invariants."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, deterministic_item_id
from docgrain_domain.canonical.visuals import (
    VisualDecision,
    VisualPreviewRequest,
    preview_visual_review,
    verify_inventory,
    visual_inventory,
)
from docgrain_worker.local_visual_ocr import (
    LocalOCRSession,
    prepare_local_ocr,
    validate_local_ocr_proposal,
)
from tests.fixtures.canonical.generate import annotation, generic_pdf


def visual_snapshot(image=None, orientation=1):
    if image is None:
        stream = BytesIO()
        exif = Image.Exif()
        exif[274] = orientation
        Image.new("RGB", (100, 60), "white").save(stream, format="JPEG", exif=exif)
        image = stream.getvalue()
    source = b"pinned PDF source"
    value = generic_pdf()
    value["schema_version"] = "0.2.0"
    value["source_version"].update(
        content_sha256=sha256(source).hexdigest(), byte_size=len(source)
    )
    artifact_id = "artifact-image"
    value["artifacts"] = [
        {
            "id": artifact_id,
            "role": "source-image",
            "storage_uri": "review://image",
            "content_sha256": sha256(image).hexdigest(),
            "byte_size": len(image),
            "mime_type": "image/jpeg",
        }
    ]
    for index in range(2):
        key = f"visual:{index}"
        node_id = deterministic_item_id(value["document_id"], "asset", key)
        value["structure"].append(
            {
                "id": node_id,
                "identity_key": key,
                "kind": "asset",
                "artifact_id": artifact_id,
                "description": None,
                "annotation": annotation("evidence-table"),
            }
        )
        next(n for n in value["structure"] if n["id"] == value["root_node_id"])[
            "children"
        ].append(node_id)
    return CanonicalKnowledgeSnapshot.model_validate(value), source, image


def test_inventory_is_pinned_deterministic_and_duplicates_are_not_decorative():
    snapshot, _, _ = visual_snapshot()
    before = snapshot.model_dump(mode="json")
    inventory = visual_inventory(snapshot)
    assert inventory == visual_inventory(snapshot)
    assets = [r for r in inventory.regions if r.node_kind == "asset"]
    assert [r.classification for r in assets] == ["unknown", "unknown"]
    assert assets[1].duplicate_of == assets[0].node_id
    assert "visual_meaning_unresolved" in assets[1].actions
    assert snapshot.model_dump(mode="json") == before
    bad = inventory.model_copy(deep=True)
    bad.regions[1].classification = "decorative"
    with pytest.raises(ValueError, match="inventory differs"):
        verify_inventory(snapshot, bad)


def test_manual_preview_is_proposed_and_never_closes_gaps_or_changes_source():
    snapshot, _, _ = visual_snapshot()
    inventory = visual_inventory(snapshot)
    region = next(r for r in inventory.regions if r.node_kind == "asset")
    decision = VisualDecision(
        region_id=region.id,
        classification="logo",
        reviewer_id="local-reviewer",
        reason="Logo lettering checked against source image",
    )
    request = VisualPreviewRequest(
        inventory_id=inventory.id,
        snapshot_sha256=inventory.snapshot_sha256,
        decisions=[decision],
    )
    preview = preview_visual_review(snapshot, request)
    assert preview.review_status == "proposed"
    assert preview.inventory.regions == inventory.regions
    assert preview_visual_review(snapshot, request) == preview
    with pytest.raises(ValueError, match="another source"):
        preview_visual_review(
            snapshot, request.model_copy(update={"inventory_id": "stale"})
        )
    with pytest.raises(ValueError, match="duplicate"):
        preview_visual_review(
            snapshot, request.model_copy(update={"decisions": [decision, decision]})
        )
    table = next(r for r in inventory.regions if r.node_kind == "table")
    with pytest.raises(ValueError, match="native table/chart"):
        preview_visual_review(
            snapshot,
            request.model_copy(
                update={
                    "decisions": [decision.model_copy(update={"region_id": table.id})]
                }
            ),
        )
    with pytest.raises(ValueError, match="nonblank"):
        VisualDecision(
            region_id=region.id,
            classification="photo",
            reviewer_id=" ",
            reason="reason",
        )


@pytest.mark.parametrize("orientation", range(1, 9))
def test_ocr_artifact_boxes_retain_original_exif_frame_and_cache_rebinds(
    orientation, monkeypatch
):
    snapshot, source, image = visual_snapshot(orientation=orientation)
    inventory = visual_inventory(snapshot)
    assets = [r for r in inventory.regions if r.node_kind == "asset"]
    calls = []

    class Reader:
        def readtext(self, prepared, **options):
            calls.append(options)
            with Image.open(BytesIO(prepared)) as frame:
                width, height = frame.size
            return [
                (
                    [
                        [width * 0.1, height * 0.2],
                        [width * 0.5, height * 0.2],
                        [width * 0.5, height * 0.6],
                        [width * 0.1, height * 0.6],
                    ],
                    "İzmir 127",
                    0.5,
                )
            ]

    session = LocalOCRSession()
    session._reader = Reader()
    session._profile = {
        "review_threshold": 0.8,
        "device": "cpu",
        "download_enabled": False,
    }
    from docgrain_worker import local_visual_ocr

    monkeypatch.setattr(local_visual_ocr, "verified_profile", lambda: session._profile)
    first = session.extract(snapshot, inventory, assets[0].id, source, image)
    second = session.extract(snapshot, inventory, assets[1].id, source, image)
    assert len(calls) == 1 and second["cache_hit"] and not first["cache_hit"]
    assert first["request"]["target_node_id"] != second["request"]["target_node_id"]
    assert (
        first["visible_text"] == ["İzmir 127"] and first["visual_description"] is None
    )
    locator = first["words"][0]["locator"]
    assert (locator["width_px"], locator["height_px"], locator["exif_orientation"]) == (
        100,
        60,
        orientation,
    )
    assert "ocr_low_score" in first["uncertainties"]
    validate_local_ocr_proposal(snapshot, inventory, second, source, image)
    bad = deepcopy(second)
    bad["words"][0]["text"] = "invented"
    with pytest.raises(ValueError, match="literal OCR"):
        validate_local_ocr_proposal(snapshot, inventory, bad, source, image)


def test_ocr_rejects_wrong_source_binary_stale_inventory_and_nonraster_chart():
    snapshot, source, image = visual_snapshot()
    inventory = visual_inventory(snapshot)
    region = next(r for r in inventory.regions if r.node_kind == "asset")
    for wrong_source, wrong_image in [(b"changed", image), (source, b"changed")]:
        with pytest.raises(ValueError, match="pinned"):
            prepare_local_ocr(snapshot, inventory, region.id, wrong_source, wrong_image)
    changed = snapshot.model_copy(deep=True)
    changed.knowledge_revision = changed.knowledge_revision.model_copy(
        update={"id": "new-processing-revision"}
    )
    with pytest.raises(ValueError, match="inventory differs"):
        prepare_local_ocr(changed, inventory, region.id, source, image)
    table = next(r for r in inventory.regions if r.node_kind == "table")
    with pytest.raises(ValueError, match="raster artifact"):
        prepare_local_ocr(snapshot, inventory, table.id, source, image)


def test_blank_ocr_and_engine_failure_are_explicit_not_visual_acceptance():
    snapshot, source, image = visual_snapshot()
    inventory = visual_inventory(snapshot)
    region = next(r for r in inventory.regions if r.node_kind == "asset")
    session = LocalOCRSession()
    session._profile = {"review_threshold": 0.8}
    session._reader = SimpleNamespace(readtext=lambda *_args, **_kwargs: [])
    result = session.extract(snapshot, inventory, region.id, source, image)
    assert (
        result["execution_status"] == "done"
        and "no_readable_text" in result["uncertainties"]
    )
    assert "visual_meaning_unresolved" in result["uncertainties"]

    def fail(*_args, **_kwargs):
        raise RuntimeError("local engine failure")

    session._cache.clear()
    session._reader = SimpleNamespace(readtext=fail)
    result = session.extract(snapshot, inventory, region.id, source, image)
    assert (
        result["execution_status"] == "failed"
        and result["words"] == []
        and not session._cache
    )


def test_visual_api_preview_is_pure_and_rejects_missing_stale_and_demo(monkeypatch):
    from tests.unit.test_knowledge_api import client, setup_live
    from docgrain_api.routers import knowledge

    actual_store = knowledge._store
    snapshot, store = setup_live(monkeypatch)
    before = snapshot.model_dump(mode="json")
    path = f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}/visuals"
    inventory = client.get(path).json()
    assert inventory["revision_id"] == snapshot.knowledge_revision.id
    body = {
        "inventory_id": inventory["id"],
        "snapshot_sha256": inventory["snapshot_sha256"],
        "decisions": [
            {
                "region_id": inventory["regions"][0]["id"],
                "classification": "table",
                "reviewer_id": "reviewer",
                "reason": "Cells checked",
            }
        ],
    }
    response = client.post(path + "/preview", json=body)
    assert (
        response.status_code == 200 and response.json()["review_status"] == "proposed"
    )
    assert store.snapshot.model_dump(mode="json") == before
    body["inventory_id"] = "stale"
    assert client.post(path + "/preview", json=body).status_code == 409
    assert client.get("/v1/knowledge/revisions/missing/visuals").status_code == 404
    from docgrain_api.settings import get_settings

    monkeypatch.setattr(get_settings(), "use_fixtures", True)
    monkeypatch.setattr(knowledge, "_store", actual_store)
    assert client.get(path).status_code == 404
