"""Additive company catalog and model settings; never store credential values."""

from __future__ import annotations

from uuid import uuid4

import psycopg

from . import repository
from .settings import get_settings


def initialize(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workspace_catalog (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS workspace_model_settings (
                workspace_id TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT false,
                base_url TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
                credential_id TEXT NOT NULL DEFAULT '',
                settings_version BIGINT NOT NULL CHECK (settings_version > 0)
            );
        """)


def _require_writable() -> None:
    if get_settings().use_fixtures:
        raise RuntimeError("demo repository is read-only")


def create_workspace(name: str) -> dict[str, object]:
    _require_writable()
    workspace_id = f"ws_{uuid4().hex}"
    with repository._connection() as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO workspace_catalog (id, name) VALUES (%s, %s)",
                       (workspace_id, name))
    return {"id": workspace_id, "name": name, "documents": 0}


def workspace_exists(workspace_id: str) -> bool:
    return any(item["id"] == workspace_id for item in repository.list_workspaces())


def read_model(workspace_id: str) -> dict[str, object] | None:
    if get_settings().use_fixtures:
        return None
    with repository._connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT enabled, base_url, model, credential_id, settings_version "
                       "FROM workspace_model_settings WHERE workspace_id = %s", (workspace_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def save_model(workspace_id: str, values: dict[str, object]) -> dict[str, object]:
    _require_writable()
    with repository._connection() as connection, connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO workspace_model_settings
                (workspace_id, enabled, base_url, model, credential_id, settings_version)
            VALUES (%s, %s, %s, %s, %s, 1)
            ON CONFLICT (workspace_id) DO UPDATE SET
                enabled = EXCLUDED.enabled, base_url = EXCLUDED.base_url,
                model = EXCLUDED.model, credential_id = EXCLUDED.credential_id,
                settings_version = workspace_model_settings.settings_version + 1
            RETURNING enabled, base_url, model, credential_id, settings_version
        """, (workspace_id, values["enabled"], values["base_url"], values["model"],
              values["credential_id"]))
        return dict(cursor.fetchone())
