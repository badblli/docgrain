"""Job status. One durable job per document version."""

from __future__ import annotations

from docgrain_domain import Job, JobStatus
from fastapi import APIRouter, HTTPException, status

from .. import fixtures

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.get("", response_model=list[Job])
def list_jobs(job_status: JobStatus | None = None) -> list[Job]:
    if job_status is None:
        return fixtures.JOBS
    return [job for job in fixtures.JOBS if job.status is job_status]


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    job = next((j for j in fixtures.JOBS if j.id == job_id), None)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job
