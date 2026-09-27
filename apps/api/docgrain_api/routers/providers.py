"""Provider configuration inventory; no connectivity probes are performed."""

from __future__ import annotations

from docgrain_domain import ProviderHealth
from fastapi import APIRouter

from ..settings import get_settings

router = APIRouter(prefix="/v1/providers", tags=["providers"])


@router.get("/health", response_model=list[ProviderHealth])
def provider_health() -> list[ProviderHealth]:
    settings = get_settings()
    gemini_configured = bool(settings.gemini_api_key.strip())
    return [
        ProviderHealth(
            interface="PageRenderer",
            implementation="pymupdf",
            healthy=None,
            location="local",
            note="PDF page rendering configured at 200 DPI; not probed.",
        ),
        ProviderHealth(
            interface="VisionProvider",
            implementation=settings.gemini_model,
            healthy=None if gemini_configured else False,
            location="hosted",
            note=(
                "Primary per-page extraction configured; credentials/model not verified."
                if gemini_configured
                else "GEMINI_API_KEY is not configured; Docling fallback is active."
            ),
        ),
        ProviderHealth(
            interface="DocumentParser",
            implementation="docling-fallback",
            healthy=None,
            location="local",
            note="Current fallback when Gemini is unconfigured; not probed. Target: structural primary.",
        ),
        ProviderHealth(
            interface="EmbeddingProvider",
            implementation="not-configured",
            healthy=False,
            location="local",
            note="Embedding and retrieval indexing are not implemented yet.",
        ),
        ProviderHealth(
            interface="VectorIndex",
            implementation="qdrant",
            healthy=False,
            location="docker",
            note="Index adapter is not implemented; container availability is not checked.",
        ),
        ProviderHealth(
            interface="ObjectStorage",
            implementation="minio",
            healthy=None,
            location="docker",
            note=f"Configured bucket: {settings.s3_bucket}; connectivity not checked.",
        ),
    ]
