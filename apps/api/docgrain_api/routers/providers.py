"""Provider health. Which adapter is wired in, and is it answering."""

from __future__ import annotations

from docgrain_domain import ProviderHealth
from fastapi import APIRouter

from .. import fixtures

router = APIRouter(prefix="/v1/providers", tags=["providers"])


@router.get("/health", response_model=list[ProviderHealth])
def provider_health() -> list[ProviderHealth]:
    return fixtures.PROVIDERS
