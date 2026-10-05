"""Actual pinned CPU reader, no Docling pipeline and no remote provider."""

import importlib.util
from io import BytesIO
from pathlib import Path

import pytest
from docgrain_domain.canonical.visuals import visual_inventory
from docgrain_worker.local_visual_ocr import (
    LocalOCRSession,
    validate_local_ocr_proposal,
)
from PIL import Image

from tests.unit.test_n3_visuals import visual_snapshot

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("easyocr") is None, reason="pinned EasyOCR worker required"
)


def test_actual_selected_ocr_reuses_reader_and_retains_exif_source_frame():
    image = Image.open(Path("tests/fixtures/structural/printed-tr-en.png"))
    stream = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    image.transpose(Image.Transpose.ROTATE_90).save(
        stream, format="JPEG", quality=98, exif=exif
    )
    snapshot, source, binary = visual_snapshot(stream.getvalue())
    inventory = visual_inventory(snapshot)
    regions = [r for r in inventory.regions if r.node_kind == "asset"]
    before = snapshot.model_dump(mode="json")
    session = LocalOCRSession()
    first = session.extract(snapshot, inventory, regions[0].id, source, binary)
    second = session.extract(snapshot, inventory, regions[1].id, source, binary)
    assert first["execution_status"] == "done" and second["cache_hit"]
    assert "ODA SAYISI 127" in first["visible_text"]
    assert "Room area 42 m2" in first["visible_text"]
    assert all(w["locator"]["exif_orientation"] == 6 for w in first["words"])
    assert (
        first["producer"]["device"] == "cpu"
        and not first["producer"]["download_enabled"]
    )
    assert first["visual_description"] is None and first["review_status"] == "proposed"
    validate_local_ocr_proposal(snapshot, inventory, second, source, binary)
    assert snapshot.model_dump(mode="json") == before
