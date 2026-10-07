"""Company creation and model configuration, mounted by documents.workspaces_router."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import workspace_settings as service
from .. import workspace_settings_repository as store
from ..settings import get_settings

router = APIRouter(prefix="/v1/workspaces")


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    name: str = Field(min_length=1, max_length=200)


async def _body(request: Request, schema: type[BaseModel]) -> BaseModel:
    # FastAPI's default validation includes the rejected input, which may contain a raw key.
    try:
        return schema.model_validate(await request.json())
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(422, "Alanları kontrol edin; yalnız izinli ayarları gönderin.") from None


def _call(function, *args):
    try:
        return function(*args)
    except service.ModelSettingsError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None


@router.post("", status_code=201)
async def create_workspace(request: Request) -> dict[str, object]:
    if get_settings().use_fixtures:
        raise HTTPException(409, "Örnek görünümde çalışma alanı oluşturulamaz.")
    payload = await _body(request, WorkspaceCreate)
    name = payload.name.strip()
    if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise HTTPException(422, "Çalışma alanı için bir ad yazın.")
    return store.create_workspace(name)


@router.get("/{ws}/model")
def get_model(ws: str) -> dict[str, object]:
    return _call(service.get_workspace_model, ws)


@router.put("/{ws}/model")
async def put_model(ws: str, request: Request) -> dict[str, object]:
    payload = await _body(request, service.ModelUpdate)
    return _call(service.put_workspace_model, ws, payload)


@router.get("/{ws}/model/profiles")
def get_profiles(ws: str) -> list[dict[str, object]]:
    return _call(service.list_profiles, ws)
