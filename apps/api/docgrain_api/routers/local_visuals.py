"""Explicit source-bound local visual proposals; no canonical/head/coverage writes."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from time import perf_counter

from docgrain_domain.canonical.lifecycle import digest
from docgrain_domain.canonical.locations import StrictModel
from fastapi import APIRouter, HTTPException
from minio.error import S3Error
from PIL import Image, UnidentifiedImageError
from pydantic import Field

from .. import local_vision
from ..review_publication import StorageIntegrityError, verified_source
from ..settings import get_settings
from ..storage import storage_client
from .chat import _fetch_image, _image_artifact, _node_evidence_ids, _snapshot_digest
from .knowledge import get_revision

router = APIRouter(prefix="/v1/knowledge", tags=["local visual review"])
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


class LocalVisualRequest(StrictModel):
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_id: str = Field(min_length=1, max_length=200)


class LocalVisualConfig(StrictModel):
    enabled: bool
    ready: bool
    model: str
    profile_id: str


class LocalVisualProposal(StrictModel):
    id: str
    review_status: str = "proposed"
    revision_id: str
    snapshot_sha256: str
    node_id: str
    artifact_id: str
    binary_sha256: str
    source_sha256: str
    evidence_ids: list[str]
    profile_id: str
    model: str
    model_sha256: str
    projector_sha256: str
    prompt_sha256: str
    classification: str
    description: str | None
    visible_text: list[str]
    uncertainties: list[str]
    warnings: list[str]
    elapsed_ms: int


@router.get("/revisions/{revision_id}/visuals/local/config", response_model=LocalVisualConfig)
def config(revision_id: str):
    settings = get_settings()
    if not settings.use_fixtures:
        get_revision(revision_id)
    enabled = settings.docgrain_local_vision_enabled and not settings.use_fixtures
    return LocalVisualConfig(enabled=enabled, ready=enabled and local_vision.ready(),
                             model=local_vision.MODEL, profile_id=local_vision.PROFILE_ID)


def image_geometry(data: bytes, mime: str) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != {"image/png": "PNG", "image/jpeg": "JPEG"}[mime]:
                raise ValueError("Image format mismatch")
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Image pixel limit")
            image.verify()
            return width, height
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError, KeyError):
        raise HTTPException(422, "Görsel biçimi veya boyutu doğrulanamadı.") from None


@router.post("/revisions/{revision_id}/visuals/local/proposals", response_model=LocalVisualProposal)
def propose(revision_id: str, request: LocalVisualRequest):
    settings = get_settings()
    if settings.use_fixtures:
        raise HTTPException(409, "Demo modunda yerel görsel inceleme kullanılamaz.")
    if not settings.docgrain_local_vision_enabled:
        raise HTTPException(503, "Yerel görsel modeli bu sunucuda kapalı.")
    snapshot = get_revision(revision_id)
    if _snapshot_digest(snapshot) != request.snapshot_sha256:
        raise HTTPException(409, "Revision içeriği uyuşmuyor; güncel revision'ı yükleyin.")
    node = next((node for node in snapshot.structure if node.id == request.node_id), None)
    artifact = _image_artifact(snapshot, node) if node is not None else None
    if artifact is None or not _node_evidence_ids(node):
        raise HTTPException(422, "Kaynak kanıtı olan JPEG/PNG görseli seçin.")
    if artifact.byte_size > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Görsel 4 MB sınırını aşıyor.")
    if not local_vision.INFERENCE_LOCK.acquire(blocking=False):
        raise HTTPException(429, "Yerel model başka bir görseli inceliyor; tamamlanınca tekrar deneyin.")
    started = perf_counter()
    try:
        try:
            verified_source(storage_client(), settings.s3_bucket, snapshot)
            data = _fetch_image(snapshot, artifact)
        except StorageIntegrityError:
            raise HTTPException(409, "Kaynak veya görsel dosyasının kimliği doğrulanamadı.") from None
        except (S3Error, OSError):
            raise HTTPException(503, "Kaynak veya görsel dosyası okunamadı.") from None
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Görsel 4 MB sınırını aşıyor.")
        width, height = image_geometry(data, artifact.mime_type)
        try:
            observation = local_vision.generate(artifact.mime_type, data)
        except local_vision.LocalUnavailable:
            raise HTTPException(503, "Yerel model hazır değil veya isteği tamamlayamadı.") from None
        except local_vision.LocalMalformed:
            raise HTTPException(502, "Yerel model önerisi doğrulanamadı; açıklama kaydedilmedi.") from None
        payload = {
            "revision_id": revision_id, "snapshot_sha256": request.snapshot_sha256, "node_id": node.id,
            "artifact_id": artifact.id, "binary_sha256": artifact.content_sha256,
            "source_sha256": snapshot.source_version.content_sha256,
            "evidence_ids": sorted(_node_evidence_ids(node)),
            "profile_id": local_vision.PROFILE_ID, "model": local_vision.MODEL,
            "model_sha256": local_vision.PROFILE["files"][0]["sha256"],
            "projector_sha256": local_vision.PROFILE["files"][1]["sha256"],
            "prompt_sha256": sha256(local_vision.PROMPT.encode()).hexdigest(),
            **observation.model_dump(mode="json"),
        }
        warnings = ["Yerel model önerisidir; kaynakla doğrulamadan kesin bilgi olarak kaydetmeyin.",
                    "Öneri revision, kapsam veya onay durumunu değiştirmez; embedding üretmez.",
                    "Metin çıkarımı ayrı OCR aşamasına aittir; görsel modeli yazıları doğrulamaz.",
                    "Modelin görsel token sınırı küçük yazı ve geometri ayrıntılarını kaybettirebilir."]
        if min(width, height) < 256:
            warnings.append("Kaynak görsel küçük; okunmayan yazı ve belirsiz nesneler çıkarılamaz.")
        return LocalVisualProposal(id="local_visual_" + digest(payload)[:32], **payload,
                                   warnings=warnings, elapsed_ms=round((perf_counter() - started) * 1000))
    finally:
        local_vision.INFERENCE_LOCK.release()
