"""Selected, source-pinned local OCR with one reusable CPU reader per session.

Literal text is an unreviewed observation, never a visual description. This
module contains no provider client, database writer or publication path.
"""

from __future__ import annotations

import copy
import math
import numbers
import time
from hashlib import sha256
from threading import RLock

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.lifecycle import digest
from docgrain_domain.canonical.locations import ImageRegionLocator, StrictModel
from docgrain_domain.canonical.visuals import VisualInventory, verify_inventory
from docgrain_domain.source_format import SourceFormat, verify_format
from pydantic import Field

from .image_geometry import image_locator, prepare_image
from .ocr import verified_profile

OPTIONS = {
    "decoder": "greedy",
    "detail": 1,
    "paragraph": False,
    "batch_size": 1,
    "workers": 0,
    "canvas_size": 2560,
    "mag_ratio": 1.0,
}
MAX_PIXELS = 20_000_000
MAX_WORDS = 10000


class OCRWord(StrictModel):
    text: str = Field(min_length=1)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    score_method: str
    artifact_id: str
    locator: ImageRegionLocator


def producer_profile(profile: dict) -> dict:
    return {
        **profile,
        "mode": "selected_artifact",
        "profile_version": "n3-local-1",
        "options": OPTIONS.copy(),
        "max_pixels": MAX_PIXELS,
        "max_words": MAX_WORDS,
    }


def prepare_local_ocr(
    snapshot: CanonicalKnowledgeSnapshot,
    inventory: VisualInventory,
    region_id: str,
    source_bytes: bytes,
    image_bytes: bytes,
) -> tuple[dict, bytes]:
    verify_inventory(snapshot, inventory)
    source = snapshot.source_version
    if (
        sha256(source_bytes).hexdigest() != source.content_sha256
        or len(source_bytes) != source.byte_size
    ):
        raise ValueError("source bytes differ from pinned source")
    region = next((r for r in inventory.regions if r.id == region_id), None)
    if region is None or "local_ocr_available" not in region.actions:
        raise ValueError(
            "selected region lacks a source-bound raster artifact for local OCR"
        )
    artifact = next(a for a in snapshot.artifacts if a.id == region.artifact_id)
    if (
        sha256(image_bytes).hexdigest() != artifact.content_sha256
        or len(image_bytes) != artifact.byte_size
    ):
        raise ValueError("selected binary differs from pinned artifact")
    verify_format(
        image_bytes,
        SourceFormat.PNG if artifact.mime_type == "image/png" else SourceFormat.JPEG,
    )
    from PIL import Image
    from io import BytesIO

    with Image.open(BytesIO(image_bytes)) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError("selected image exceeds local OCR pixel bound")
    prepared, geometry = prepare_image(image_bytes)
    request = {
        "inventory_id": inventory.id,
        "snapshot_sha256": inventory.snapshot_sha256,
        "document_id": inventory.document_id,
        "workspace_id": inventory.workspace_id,
        "revision_id": inventory.revision_id,
        "source_sha256": inventory.source_sha256,
        "region_id": region.id,
        "target_node_id": region.node_id,
        "evidence_ids": region.evidence_ids,
        "artifact_id": artifact.id,
        "binary_sha256": artifact.content_sha256,
        "input_sha256": sha256(prepared).hexdigest(),
        "image_geometry": geometry,
    }
    return request, prepared


FAILURES = {
    "reader_initialization_failed",
    "recognizer_failed",
    "invalid_recognizer_output",
}


class _ReaderInitError(Exception):
    pass


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("OCR observation number is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("OCR observation number is not finite")
    return result


def _validated_observations(observed, size: tuple[int, int]) -> list:
    """Return plain (polygon, text, score) rows inside the prepared frame."""
    if not isinstance(observed, (list, tuple)):
        raise ValueError("OCR output must be a list of rows")
    width, height = size
    rows = []
    for row in observed:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ValueError("OCR row must be polygon, text and score")
        polygon, text, score = row
        if not isinstance(text, str):
            raise ValueError("OCR text must be a string")
        score = _number(score)
        if not 0 <= score <= 1:
            raise ValueError("OCR score outside 0..1")
        try:
            points = [list(point) for point in polygon]
        except TypeError as exc:
            raise ValueError("OCR polygon is malformed") from exc
        if len(points) != 4 or any(len(point) != 2 for point in points):
            raise ValueError("OCR polygon must have four x,y points")
        points = [[_number(x), _number(y)] for x, y in points]
        xs, ys = zip(*points, strict=True)
        # Same subpixel tolerance as image_locator; clamp inside the frame.
        if (
            min(xs) < -1e-6 * width
            or max(xs) > width * (1 + 1e-6)
            or min(ys) < -1e-6 * height
            or max(ys) > height * (1 + 1e-6)
        ):
            raise ValueError("OCR polygon lies outside the image frame")
        points = [
            [min(max(x, 0.0), float(width)), min(max(y, 0.0), float(height))]
            for x, y in points
        ]
        xs, ys = zip(*points, strict=True)
        if max(xs) <= min(xs) or max(ys) <= min(ys):
            raise ValueError("OCR polygon is degenerate")
        rows.append((points, str(text), score))
    return rows


def _failed(
    request: dict,
    profile: dict,
    category: str,
    started: float,
    load_s: float,
    ocr_s: float,
) -> dict:
    return {
        "format": "docgrain.local-ocr-proposal",
        "version": "1.0.0",
        "review_status": "proposed",
        "execution_status": "failed",
        "request": request,
        "producer": profile,
        "words": [],
        "visible_text": [],
        "visual_description": None,
        "uncertainties": ["local_ocr_failed"],
        "failure": category,
        "cache_hit": False,
        "observation_sha256": None,
        "timings_s": {
            "reader_load": round(load_s, 4),
            "ocr": round(ocr_s, 4),
            "total": round(time.perf_counter() - started, 4),
        },
        "limitations": ["No canonical or published output was changed."],
    }


class LocalOCRSession:
    """CPU only; memory cache stores OCR facts, never source/review bindings."""

    def __init__(self):
        self._reader = None
        self._profile = None
        self._cache = {}
        self._lock = RLock()

    def _load(self):
        if self._reader is None:
            # A missing or unverified profile propagates: the session fails closed.
            self._profile = verified_profile()
            try:
                from .ocr import model_directory
                import easyocr
                import torch

                torch.set_num_threads(2)
                self._reader = easyocr.Reader(
                    ["tr", "en"],
                    gpu=False,
                    model_storage_directory=str(model_directory()),
                    download_enabled=False,
                    verbose=False,
                )
            except Exception as exc:
                raise _ReaderInitError from exc

    def extract(
        self,
        snapshot: CanonicalKnowledgeSnapshot,
        inventory: VisualInventory,
        region_id: str,
        source_bytes: bytes,
        image_bytes: bytes,
    ) -> dict:
        started = time.perf_counter()
        request, prepared = prepare_local_ocr(
            snapshot, inventory, region_id, source_bytes, image_bytes
        )
        metadata = request["image_geometry"]
        size = (metadata["input_width_px"], metadata["input_height_px"])
        with self._lock:
            loading = time.perf_counter()
            try:
                self._load()
            except _ReaderInitError:
                load_s = time.perf_counter() - loading
                return _failed(
                    request,
                    producer_profile(self._profile),
                    "reader_initialization_failed",
                    started,
                    load_s,
                    0.0,
                )
            load_s = time.perf_counter() - loading
            profile = producer_profile(self._profile)
            key = digest([request["input_sha256"], profile])
            hit = key in self._cache
            inference = time.perf_counter()
            if hit:
                raw = copy.deepcopy(self._cache[key])
            else:
                try:
                    observed = self._reader.readtext(prepared, **OPTIONS)
                except Exception:
                    return _failed(
                        request,
                        profile,
                        "recognizer_failed",
                        started,
                        load_s,
                        time.perf_counter() - inference,
                    )
                try:
                    raw = _validated_observations(observed, size)
                except ValueError:
                    return _failed(
                        request,
                        profile,
                        "invalid_recognizer_output",
                        started,
                        load_s,
                        time.perf_counter() - inference,
                    )
                # Bound session memory and retain per-source bindings separately.
                if len(raw) <= MAX_WORDS:
                    if len(self._cache) >= 64:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = copy.deepcopy(raw)
            inference_s = time.perf_counter() - inference
        words = []
        uncertainties = []
        for polygon, text, score in raw[:MAX_WORDS]:
            if not text.strip():
                continue
            xs, ys = zip(*polygon, strict=True)
            locator = image_locator(
                {
                    "l": min(xs),
                    "r": max(xs),
                    "t": min(ys),
                    "b": max(ys),
                    "coord_origin": "TOPLEFT",
                },
                size,
                metadata,
            )
            words.append(
                OCRWord(
                    text=text,
                    score=score,
                    score_method="easyocr-recognition",
                    artifact_id=request["artifact_id"],
                    locator=locator,
                ).model_dump(mode="json")
            )
        if len(raw) > MAX_WORDS:
            uncertainties.append("ocr_word_limit")
        if not words:
            uncertainties.append("no_readable_text")
        if any(w["score"] < profile["review_threshold"] for w in words):
            uncertainties.append("ocr_low_score")
        uncertainties.append("visual_meaning_unresolved")
        return {
            "format": "docgrain.local-ocr-proposal",
            "version": "1.0.0",
            "review_status": "proposed",
            "execution_status": "done",
            "request": request,
            "producer": profile,
            "words": words,
            "visible_text": [w["text"] for w in words],
            "visual_description": None,
            "uncertainties": uncertainties,
            "cache_hit": hit,
            "observation_sha256": digest([request["input_sha256"], profile, words]),
            "timings_s": {
                "reader_load": round(load_s, 4),
                "ocr": round(inference_s, 4),
                "total": round(time.perf_counter() - started, 4),
            },
            "limitations": [
                "Boxes refer to original artifact pixels; source page/part evidence is retained separately.",
                "Literal OCR and recognition scores do not certify text, table structure or visual meaning.",
                "No provider call, canonical revision, publication or embedding was created.",
            ],
        }


def validate_local_ocr_proposal(
    snapshot: CanonicalKnowledgeSnapshot,
    inventory: VisualInventory,
    proposal: dict,
    source_bytes: bytes,
    image_bytes: bytes,
) -> None:
    if not isinstance(proposal, dict):
        raise ValueError("local OCR proposal must be an object")
    if (
        proposal.get("format") != "docgrain.local-ocr-proposal"
        or proposal.get("version") != "1.0.0"
    ):
        raise ValueError("unsupported local OCR proposal")
    claimed = proposal.get("request")
    if not isinstance(claimed, dict) or not isinstance(claimed.get("region_id"), str):
        raise ValueError("local OCR proposal request is malformed")
    request, _ = prepare_local_ocr(
        snapshot, inventory, claimed["region_id"], source_bytes, image_bytes
    )
    if request != claimed:
        raise ValueError(
            "local OCR proposal belongs to another source/revision/artifact"
        )
    status = proposal.get("execution_status")
    if not isinstance(status, str) or status not in {"done", "failed"}:
        raise ValueError("invalid local OCR execution status")
    if (
        proposal.get("review_status") != "proposed"
        or proposal.get("visual_description") is not None
    ):
        raise ValueError("local OCR cannot certify or describe visual meaning")
    if proposal.get("producer") != producer_profile(verified_profile()):
        raise ValueError("local OCR proposal uses another processing profile")
    words = proposal.get("words")
    if not isinstance(words, list) or len(words) > MAX_WORDS:
        raise ValueError("invalid local OCR word count")
    geometry = request["image_geometry"]
    for word in words:
        word = OCRWord.model_validate(word)
        if (
            word.artifact_id != request["artifact_id"]
            or word.score_method != "easyocr-recognition"
            or (
                word.locator.width_px,
                word.locator.height_px,
                word.locator.exif_orientation,
            )
            != (
                geometry["width_px"],
                geometry["height_px"],
                geometry["exif_orientation"],
            )
        ):
            raise ValueError("local OCR word differs from original artifact frame")
    if proposal.get("visible_text") != [word["text"] for word in words]:
        raise ValueError("literal OCR text differs from word observations")
    if status == "failed":
        if (
            words
            or proposal.get("visible_text")
            or proposal.get("observation_sha256") is not None
        ):
            raise ValueError("failed local OCR cannot carry observations")
        failure = proposal.get("failure")
        uncertainties = proposal.get("uncertainties")
        if (
            not isinstance(failure, str)
            or failure not in FAILURES
            or not isinstance(uncertainties, list)
            or any(not isinstance(value, str) for value in uncertainties)
            or "local_ocr_failed" not in uncertainties
        ):
            raise ValueError("failed local OCR lacks failure information")
    elif proposal.get("failure") is not None or proposal.get(
        "observation_sha256"
    ) != digest([request["input_sha256"], proposal["producer"], proposal["words"]]):
        raise ValueError("local OCR observation digest differs")
