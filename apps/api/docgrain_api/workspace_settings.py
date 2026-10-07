"""Workspace opt-in configuration and in-memory credential resolution. No model I/O."""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from . import workspace_settings_repository as store
from .settings import get_settings


class ModelSettingsError(Exception):
    """Only fixed, public messages are used here; never wrap credential exceptions."""

    def __init__(self, detail: str, status_code: int = 409):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    enabled: StrictBool = False
    base_url: str = Field(default="", max_length=2048)
    model: str = Field(default="", max_length=256)
    credential_id: str = Field(default="", max_length=128)


class CredentialProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    label: str = Field(min_length=1, max_length=128)
    api_key_env: str | None


class ResolvedWorkspaceModel(BaseModel):
    """Pass directly to a model client. Never serialize or enqueue this object."""

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    enabled: bool
    base_url: str
    model: str
    api_key: str = Field(repr=False, exclude=True)
    settings_version: int


def _profiles() -> dict[str, CredentialProfile]:
    try:
        raw = json.loads(get_settings().docgrain_model_credential_profiles)
        if not isinstance(raw, dict):
            raise TypeError
        profiles = {}
        for key, value in raw.items():
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", key):
                raise ValueError
            profile = CredentialProfile.model_validate(value)
            if profile.api_key_env is not None and not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", profile.api_key_env
            ):
                raise ValueError
            profiles[key] = profile
        return profiles
    except (ValueError, TypeError, ValidationError):
        raise ModelSettingsError("Sunucudaki bağlantı seçenekleri hazırlanamadı.", 503) from None


def _ready(profile: CredentialProfile) -> bool:
    return profile.api_key_env is None or bool(os.environ.get(profile.api_key_env, "").strip())


def _require_workspace(ws: str) -> None:
    if not store.workspace_exists(ws):
        raise ModelSettingsError("Çalışma alanı bulunamadı.", 404)


def list_profiles(ws: str) -> list[dict[str, object]]:
    _require_workspace(ws)
    return [{"id": key, "label": profile.label, "ready": _ready(profile)}
            for key, profile in _profiles().items()]


def get_workspace_model(ws: str) -> dict[str, object]:
    _require_workspace(ws)
    values = store.read_model(ws) or {
        "enabled": False, "base_url": "", "model": "", "credential_id": "",
        "settings_version": 0,
    }
    profile = _profiles().get(str(values["credential_id"]))
    return {**values, "credential_ready": bool(profile and _ready(profile))}


def _valid_url(value: str) -> bool:
    if not value:
        return True
    try:
        url = urlsplit(value)
        return bool(
            url.scheme in {"http", "https"} and url.hostname and url.port != 0
            and not url.username and not url.password and "@" not in url.netloc
            and not any(char in value for char in "?#\\")
            and not re.search(r"[\s\x00-\x1f\x7f]", value)
            and "%" not in value
            and not re.search(r"(?:sk-|(?:api[_-]?)?key[=/]|token[=/]|secret[=/])",
                              url.path, re.IGNORECASE)
        )
    except ValueError:
        return False


def put_workspace_model(ws: str, update: ModelUpdate) -> dict[str, object]:
    _require_workspace(ws)
    if get_settings().use_fixtures:
        raise ModelSettingsError("Örnek görünümde ayarlar değiştirilemez.")
    values = update.model_dump()
    if any(re.search(r"[\x00-\x1f\x7f]", str(values[key]))
           for key in ("base_url", "model", "credential_id")):
        raise ModelSettingsError("Bağlantı, model adı veya bağlantı seçimi geçersiz.", 422)
    for key in ("base_url", "model", "credential_id"):
        values[key] = str(values[key]).strip()
    profiles = _profiles()
    profile = profiles.get(values["credential_id"])
    # Do not allow a server credential to be copied into persisted text fields either.
    secrets = [os.environ.get(p.api_key_env, "") for p in profiles.values() if p.api_key_env]
    if (not _valid_url(values["base_url"])
            or any(secret and secret in values[key] for secret in secrets
                   for key in ("base_url", "model", "credential_id"))
            or (values["credential_id"] and profile is None)):
        raise ModelSettingsError("Bağlantı, model adı veya bağlantı seçimi geçersiz.", 422)
    if update.enabled and (not values["base_url"] or not values["model"]
                           or profile is None or not _ready(profile)):
        raise ModelSettingsError("Açmak için bağlantı, model adı ve hazır bir seçenek seçin.", 422)
    store.save_model(ws, values)
    return get_workspace_model(ws)


def resolve_workspace_model(ws: str, expected_version: int | None = None) -> ResolvedWorkspaceModel:
    """Fail closed on disabled, missing or changed settings. Resolve key rotation at use time."""
    values = get_workspace_model(ws)
    if expected_version is not None and expected_version != values["settings_version"]:
        raise ModelSettingsError("Model ayarları değişti; işlemi yeniden başlatın.")
    profile = _profiles().get(str(values["credential_id"]))
    if (not values["enabled"] or not values["base_url"] or not values["model"]
            or not _valid_url(str(values["base_url"])) or profile is None or not _ready(profile)):
        raise ModelSettingsError("İşlem için Ayarlar'dan hazır bir model seçip açın.")
    key = os.environ.get(profile.api_key_env, "") if profile.api_key_env else ""
    if profile.api_key_env is not None and not key.strip():
        raise ModelSettingsError("İşlem için Ayarlar'dan hazır bir model seçip açın.")
    return ResolvedWorkspaceModel(
        enabled=True, base_url=str(values["base_url"]), model=str(values["model"]),
        api_key=key, settings_version=int(values["settings_version"]),
    )
