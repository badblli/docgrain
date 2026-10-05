"""Input admission, original image coordinates and historical publication compatibility."""

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import jsonschema
import pytest
from docgrain_domain.canonical import (
    CanonicalKnowledgeSnapshot,
    ImageRegionLocator,
    NormalizedBox,
)
from docgrain_domain.canonical.ai_output import AIOutput, output_bundle, output_schema
from docgrain_domain.canonical.schema import (
    generated_core_schema,
    generated_core_schema_text,
)
from docgrain_domain.source_format import (
    CorruptSource,
    FormatMismatch,
    SourceFormat,
    declared_format,
    verify_format,
)
from docgrain_worker.image_geometry import prepare_image, transform_box
from PIL import Image
from pydantic import ValidationError

from tests.fixtures.lifecycle import mapped_snapshot
from tests.unit.test_m1b_api import _register, client


@pytest.mark.parametrize("name", ["a.PNG", "a.jpg", "a.JPEG"])
def test_image_admission_requires_matching_mime_signature_and_full_decode(name):
    fmt = SourceFormat.PNG if name.lower().endswith("png") else SourceFormat.JPEG
    mime = "image/png" if fmt is SourceFormat.PNG else "image/jpeg"
    data = BytesIO()
    Image.new("RGB", (10, 20), "white").save(
        data, format="PNG" if fmt is SourceFormat.PNG else "JPEG"
    )
    verify_format(data.getvalue(), declared_format(name, mime))
    verify_format(data.getvalue(), declared_format(name, "application/octet-stream"))
    with pytest.raises(FormatMismatch):
        declared_format(name, "application/pdf")
    with pytest.raises(FormatMismatch):
        verify_format(b"%PDF-1.7", fmt)
    with pytest.raises(CorruptSource):
        verify_format(data.getvalue()[:12], fmt)


def test_image_upload_gate_and_original_bytes(monkeypatch, live_repository):
    from docgrain_api.routers import documents

    stored = []
    monkeypatch.setattr(documents, "put_upload", lambda *args: stored.append(args))
    data = Path("tests/fixtures/structural/printed-tr-en.png").read_bytes()
    registration = _register("printed.png", "image/png", len(data)).json()
    response = client.put(
        registration["upload_url"], files={"file": ("printed.png", data, "image/png")}
    )
    assert response.status_code == 201
    assert stored and stored[0][1].getvalue() == data
    bad = b"\x89PNG\r\n\x1a\nxxxx"
    registration = _register("bad.png", "image/png", len(bad)).json()
    assert (
        client.put(
            registration["upload_url"], files={"file": ("bad.png", bad, "image/png")}
        ).status_code
        == 422
    )
    assert len(stored) == 1


@pytest.mark.parametrize("orientation", range(1, 9))
def test_exif_preparation_matches_original_pixel_geometry_and_inverse(orientation):
    original = Image.new("RGB", (100, 60), "white")
    # Asymmetric colored patch tests mirrors as well as rotations.
    for x in range(10, 40):
        for y in range(12, 24):
            original.putpixel((x, y), (255, 0, 0))
    exif = Image.Exif()
    exif[274] = orientation
    stream = BytesIO()
    original.save(stream, format="PNG", exif=exif)
    data = stream.getvalue()
    prepared, metadata = prepare_image(data)
    displayed = Image.open(BytesIO(prepared))
    assert displayed.mode == "RGB"
    assert metadata["source_sha256"] == sha256(data).hexdigest()
    assert metadata["input_sha256"] == sha256(prepared).hexdigest()
    assert metadata["width_px"] == 100 and metadata["height_px"] == 60
    assert displayed.size == ((60, 100) if orientation >= 5 else (100, 60))
    box = NormalizedBox(x=0.1, y=0.2, width=0.3, height=0.2)
    oriented = transform_box(box, orientation)
    center = (
        int((oriented.x + oriented.width / 2) * displayed.width),
        int((oriented.y + oriented.height / 2) * displayed.height),
    )
    assert displayed.getpixel(center) == (255, 0, 0)
    restored = transform_box(oriented, orientation, inverse=True)
    assert restored.model_dump() == pytest.approx(box.model_dump())


def test_image_locations_are_versioned_and_original_pixels_not_pdf_pages():
    snapshot, *_ = mapped_snapshot(SourceFormat.PNG)
    assert isinstance(snapshot.evidence[0].locator, ImageRegionLocator)
    jsonschema.Draft202012Validator(generated_core_schema("0.5.0")).validate(
        snapshot.model_dump(mode="json")
    )
    output, _, _, files = output_bundle(snapshot)
    assert output.version == "1.1.0"
    jsonschema.Draft202012Validator(json.loads(files["ai.schema.json"])).validate(
        json.loads(files["ai.json"])
    )
    assert all(e.locator.kind != "pdf_page" for e in output.evidence)
    with pytest.raises(ValidationError, match="1.1.0"):
        AIOutput.model_validate({**output.model_dump(mode="json"), "version": "1.0.0"})
    with pytest.raises(ValidationError, match="0.5.0"):
        # Historical snapshots have no processing spec; image evidence still must be rejected.
        historical, *_ = mapped_snapshot()
        value = historical.model_dump(mode="json")
        value["evidence"][0]["locator"] = snapshot.evidence[0].locator.model_dump(
            mode="json"
        )
        CanonicalKnowledgeSnapshot.model_validate(value)


def test_historical_schema_and_ai_publication_have_frozen_bytes():
    root = Path("packages/domain/docgrain_domain/canonical/schemas")
    for version in ("0.2.0", "0.3.0", "0.4.0"):
        assert generated_core_schema_text(version) == (
            root / f"canonical-knowledge-{version}.schema.json"
        ).read_text(encoding="utf-8")
    # Captured before N1 changed any model; prevents schema drift changing historical output hashes.
    expected = Path("tests/fixtures/canonical/ai-document-1.0.0.schema.json").read_text(
        encoding="utf-8"
    )
    assert (
        json.dumps(output_schema(), ensure_ascii=False, sort_keys=True, indent=2)
        == expected
    )


def test_ocr_checkpoint_mismatch_fails_before_model_call(monkeypatch, tmp_path):
    from docgrain_worker import ocr

    monkeypatch.setattr(ocr.importlib.metadata, "version", lambda _: "1.7.2")
    monkeypatch.setenv("DOCGRAIN_OCR_MODEL_DIR", str(tmp_path))
    (tmp_path / "craft_mlt_25k.pth").write_bytes(b"wrong-checkpoint")
    with pytest.raises(ValueError, match="checksum mismatch"):
        ocr.verified_profile()
