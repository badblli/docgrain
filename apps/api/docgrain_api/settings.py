"""Runtime settings, read from the environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache

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

    qdrant_url: str = "http://qdrant:6333"
    gemini_api_key: str = ""
    qwen_base_url: str = ""

    # While the persistence layer is unimplemented the API serves the
    # fixtures the review console was designed against.
    use_fixtures: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
