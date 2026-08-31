"""Job status. One durable job per document version."""

from __future__ import annotations

from docgrain_domain import Job, JobStatus
from fastapi import APIRouter, HTTPException, status

from .. import repository

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.get("", response_model=list[Job])
def list_jobs(job_status: JobStatus | None = None) -> list[Job]:
    jobs = repository.list_jobs()
    return jobs if job_status is None else [job for job in jobs if job.status is job_status]


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    job = repository.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job
