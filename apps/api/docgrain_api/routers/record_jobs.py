"""Explicit extraction start and durable, model-free progress reads."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .. import records_jobs
from ..workspace_settings import ModelSettingsError

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/record-jobs", tags=["records"])


class StartJob(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("", status_code=202)
def start_job(workspace_id: str, body: StartJob):
    try:
        return {"job_id": records_jobs.start(workspace_id, body.request_id)}
    except ModelSettingsError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None
    except records_jobs.JobConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except Exception:  # noqa: BLE001 - public boundary must never expose storage/credential details.
        raise HTTPException(503, "İşlem başlatılamadı; yeniden deneyin.") from None


def _read(workspace, job_id=None):
    try:
        job = records_jobs.read(workspace, job_id)
    except Exception:  # noqa: BLE001 - public boundary must never expose storage/credential details.
        raise HTTPException(503, "İşlem bilgisi alınamadı; yeniden deneyin.") from None
    if not job:
        raise HTTPException(404, "İşlem bulunamadı.")
    return {**{key: job[key] for key in (
        "job_id", "workspace_id", "status", "stage", "completed_stages", "total_stages",
        "message", "revision_id", "error_code", "updated_at", "queued_at", "started_at",
        "finished_at", "stages",
    )}, "summary": records_jobs.summary(job)}  # WP110: counts and plain notes only.


@router.get("/latest")
def latest_job(workspace_id: str):
    return _read(workspace_id)


@router.get("/{job_id}")
def get_job(workspace_id: str, job_id: str):
    return _read(workspace_id, job_id)
