"""The explicit model action; this router is relative to ai.router."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import try_ai
from ..settings import get_settings


class SafeQuestionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default error includes rejected inputs (possibly keys).
                return JSONResponse(status_code=422, content={
                    "detail": "Yalnız 1–2000 karakterlik bir soru gönderin.",
                })
        return safe_handler


router = APIRouter(route_class=SafeQuestionRoute)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Soru yazın.")
        return value.strip()


@router.post("/ask")
def ask(workspace_id: str, body: Question, request: Request):
    # No endpoint/model/mode/revision overrides, including query-string overrides.
    if request.query_params:
        raise HTTPException(422, "Yalnız soru gönderin.")
    if get_settings().use_fixtures:
        raise HTTPException(409, "Dene örnek görünümde kapalı. Kendi şirketinizi seçin.")
    # Import at action time to reuse the parent read repository without a cycle.
    from .ai import repository

    try:
        store = repository()
    except HTTPException as exc:
        raise HTTPException(409 if exc.status_code == 404 else 503,
                            try_ai.NO_PUBLICATION if exc.status_code == 404
                            else try_ai.CONNECTION) from None
    return try_ai.answer_question(workspace_id, store, question=body.question)
