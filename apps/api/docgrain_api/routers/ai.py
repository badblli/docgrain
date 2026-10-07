"""Workspace tools read immutable published artifacts without calling a model."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..ai_access import AIAccess, ToolInvalid
from ..records_repository import PackMissing, PackUnpublished
from .records import repository
from .try_ai import router as ask_router

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/ai", tags=["ai-access"])
router.include_router(ask_router)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


def _read(workspace, revision, call=None):
    try:
        access = AIAccess(repository(), workspace, revision)
        return access.call(call.name, call.arguments) if call else access.specs()
    except ToolInvalid as exc:
        raise HTTPException(422, str(exc)) from exc
    except PackMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    except PackUnpublished as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise HTTPException(503, "published artifact unavailable or invalid") from exc


@router.get("/tools")
def tools(workspace_id: str, revision_id: str | None = None):
    return _read(workspace_id, revision_id)


@router.post("/call")
def call(workspace_id: str, body: ToolCall, revision_id: str | None = None):
    return _read(workspace_id, revision_id, body)
