"""Explicit question action over wp68 approved tools, pinned once per question."""

import time
from collections.abc import Mapping

import httpx
from docgrain_access.ask import (
    AskResult,
    ModelTimeout,
    ModelUnavailable,
    OpenAICompatibleClient,
    ask_result,
)
from fastapi import HTTPException

from .ai_access import AIAccess, ToolInvalid
from .records_repository import PackMissing, PackUnpublished
from .settings import get_settings
from .workspace_settings import ModelSettingsError

CONNECTION = "Bağlantı kurulamadı. Lütfen yeniden deneyin."
TIMEOUT = "Yanıt zamanında alınamadı. Lütfen yeniden deneyin."
MODEL_OFF = "Dene için Ayarlar'dan model seçip etkinleştirin."
NO_PUBLICATION = "Henüz yayın yok. Belgeleri hazırlayıp bilgileri onaylayın."
SOURCE_FIELDS = ("id", "document_name", "locator", "quote", "document_id",
                 "source_version_id", "knowledge_revision_id")


def resolve_workspace_model(workspace_id):
    # WP92 owns this resolver. Lazy import also keeps tools/call usable before its
    # integration; there is no environment/provider fallback when it is absent.
    from .workspace_settings import resolve_workspace_model as resolve

    return resolve(workspace_id)


def _value(config, name):
    return config[name] if isinstance(config, Mapping) else getattr(config, name)


class ApprovedAccess:
    """Validate model arguments before delegation; invalid requests cannot read."""

    def __init__(self, access):
        self.access = access

    def specs(self):
        return self.access.specs()

    def call(self, name, arguments):
        if arguments.get("mode", "approved") != "approved" or any(
                key in arguments for key in ("workspace", "workspace_id", "revision", "revision_id")):
            raise ToolInvalid("only this question's approved publication is allowed")
        try:
            return self.access.call(name, arguments | {"mode": "approved"})
        except ToolInvalid:
            raise
        except PackMissing:
            # A model's unknown collection/record is a bad tool request, not an outage.
            raise ToolInvalid("record or collection unavailable") from None
        except (TimeoutError, httpx.TimeoutException):
            raise ModelTimeout("Knowledge service timed out") from None
        except (OSError, PackUnpublished, ValueError, KeyError, TypeError):
            raise ModelUnavailable("Knowledge service unavailable") from None


def answer_question(workspace_id, repository, *, question, model_factory=None):
    if get_settings().use_fixtures:
        raise HTTPException(409, "Dene örnek görünümde kapalı. Kendi şirketinizi seçin.")
    try:
        config = resolve_workspace_model(workspace_id)
        if not _value(config, "enabled") or not all(
                _value(config, key) for key in ("base_url", "model")):
            raise ValueError("model disabled or incomplete")
        base_url, model_name, key = (_value(config, name) for name in
                                     ("base_url", "model", "api_key"))
        if not isinstance(key, str):
            raise TypeError("credential missing")
    except HTTPException as exc:
        raise HTTPException(409 if exc.status_code < 500 else 503,
                            MODEL_OFF if exc.status_code < 500 else CONNECTION) from None
    except ModelSettingsError as exc:
        # WP92 fails closed with fixed public messages: off/incomplete is 409, a broken server profile 503.
        raise HTTPException(409 if exc.status_code < 500 else 503,
                            MODEL_OFF if exc.status_code < 500 else CONNECTION) from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(409, MODEL_OFF) from None
    except Exception:  # noqa: BLE001 -- Resolver failures may contain secrets; sanitize at API boundary.
        raise HTTPException(503, CONNECTION) from None

    try:
        # A new AIAccess per action resolves newest exactly once. All reads use its
        # immutable revision, including the empty-content guard via the SAME tool.
        access = AIAccess(repository, workspace_id)
        approved = ApprovedAccess(access)
        listing = approved.call("list_collections", {})
    except (PackMissing, PackUnpublished):
        raise HTTPException(409, NO_PUBLICATION) from None
    except (ModelTimeout, TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, TIMEOUT) from None
    except Exception:  # noqa: BLE001 -- Artifact/transport internals must not reach the response.
        raise HTTPException(503, CONNECTION) from None

    result = AskResult()
    if any(collection["record_count"] for collection in listing["collections"]):
        model = None
        failed = None
        settings = get_settings()
        try:
            # KULLANILMIYOR (karar 18) — WP112 replaced the fixed 20 s request timeout:
            # model = (model_factory or OpenAICompatibleClient)(base_url, model_name, key, timeout=20)
            # result = ask_result(question, approved, model)
            # WP112: per-request timeout and one deadline for the whole question (all model
            # requests, retries, tool reads and the format repair).
            limit = settings.dene_question_timeout_seconds
            deadline = time.monotonic() + limit
            model = (model_factory or OpenAICompatibleClient)(
                base_url, model_name, key, timeout=settings.dene_model_timeout_seconds,
                total_timeout=limit)
            result = ask_result(question, approved, model, deadline=deadline)
            # Even a fake/custom client must never reflect a credential into the API.
            if key and key in result.answer + str(result.sources):
                raise ModelUnavailable("Model service unavailable")
        except (ModelTimeout, TimeoutError, httpx.TimeoutException):
            failed = HTTPException(504, TIMEOUT)
        except Exception:  # noqa: BLE001 -- Never reflect model/provider output or credential errors.
            failed = HTTPException(503, CONNECTION)
        finally:
            if model is not None:
                try:
                    model.close()
                except Exception:  # noqa: BLE001 -- Client teardown can also carry transport secrets.
                    failed = HTTPException(503, CONNECTION)
        if failed:
            raise failed from None

    return {"answer": result.answer, "abstained": result.abstained,
            "workspace_id": workspace_id, "revision_id": access.revision, "mode": "approved",
            "sources": [{field: source[field] for field in SOURCE_FIELDS}
                        for source in result.sources]}
