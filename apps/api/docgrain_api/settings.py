"""Runtime settings, read from the environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    docgrain_env: str = "development"
    docgrain_log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://docgrain:change-me-locally@postgres:5432/docgrain"
    redis_url: str = "redis://redis:6379/0"

    s3_endpoint_url: str = "http://minio:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "docgrain"
    s3_access_key: str = "docgrain"
    s3_secret_key: str = "change-me-locally"
    api_public_url: str = "http://localhost:8000"

    qdrant_url: str = "http://qdrant:6333"
    gemini_chat_enabled: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.7-flash"
    qwen_base_url: str = ""
    docgrain_local_vision_enabled: bool = False
    docgrain_local_vision_url: str = "http://127.0.0.1:11435"
    docgrain_local_vision_api_key: str = ""

    # Demo is explicit and read-only. Live mode never falls back to fixtures.
    use_fixtures: bool = False
    canonical_persistence_enabled: bool = False
    records_publication_root: str = ""
    # WP110: parallel model calls while extracting records (1-4).
    records_extraction_concurrency: int = Field(default=4, ge=1, le=4)
    # Metadata only; actual credentials live in each profile's server environment.
    docgrain_model_credential_profiles: str = Field(default="{}", repr=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
