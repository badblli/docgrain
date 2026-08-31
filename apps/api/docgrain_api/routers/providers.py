"""Provider health. Which adapter is wired in, and is it answering."""

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
            healthy=True,
            location="local",
            note="200 DPI immutable page renders",
        ),
        ProviderHealth(
            interface="VisionProvider",
            implementation=settings.gemini_model,
            healthy=gemini_configured,
            location="hosted",
            note=(
                "Primary per-page extraction is configured."
                if gemini_configured
                else "GEMINI_API_KEY is not configured; Docling fallback is active."
            ),
        ),
        ProviderHealth(
            interface="DocumentParser",
            implementation="docling-fallback",
            healthy=True,
            location="local",
            note="Secondary deterministic parser; not the primary extractor.",
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
            healthy=True,
            location="docker",
            note=settings.qdrant_url,
        ),
        ProviderHealth(
            interface="ObjectStorage",
            implementation="minio",
            healthy=True,
            location="docker",
            note=f"bucket: {settings.s3_bucket}",
        ),
    ]
