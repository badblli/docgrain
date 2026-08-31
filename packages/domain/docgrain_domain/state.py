"""Job state machine.

    queued -> rendering -> extracting -> quality_check -> enriching
           -> chunking -> embedding -> indexing -> done
                                      \\-> partial
    any non-terminal state -> retrying -> previous state
    any non-terminal state -> failed

The rules live here, not in the worker, so that the API, the worker and the
tests all agree on what a legal transition is.
"""

from __future__ import annotations

from .enums import (
    STAGE_ORDER,
    TERMINAL_JOB_STATUS,
    JobStage,
    JobStatus,
    StageStatus,
    VersionStatus,
)


class JobStateError(RuntimeError):
    """Raised when a caller attempts an illegal transition."""


_ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset(
        {JobStatus.RETRYING, JobStatus.DONE, JobStatus.PARTIAL, JobStatus.FAILED}
    ),
    JobStatus.RETRYING: frozenset({JobStatus.RUNNING, JobStatus.FAILED}),
    JobStatus.DONE: frozenset(),
    JobStatus.PARTIAL: frozenset(),
    JobStatus.FAILED: frozenset(),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in _ALLOWED[current]


def assert_transition(current: JobStatus, target: JobStatus) -> None:
    if not can_transition(current, target):
        raise JobStateError(f"illegal job transition: {current} -> {target}")


def next_stage(stage: JobStage) -> JobStage | None:
    """Return the stage that follows ``stage``, or None at the end."""
    index = STAGE_ORDER.index(stage)
    if index + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[index + 1]


def is_terminal(status: JobStatus) -> bool:
    return status in TERMINAL_JOB_STATUS


def resolve_job_status(
    stage_statuses: dict[JobStage, StageStatus], has_page_failures: bool
) -> JobStatus:
    """Derive the job status from its stage results.

    A job is ``partial`` when it reached publish but individual pages failed;
    ``failed`` when a stage failed outright; ``done`` only when every stage
    finished or was legitimately skipped.
    """
    values = [stage_statuses.get(stage, StageStatus.PENDING) for stage in STAGE_ORDER]
    if StageStatus.FAILED in values:
        return JobStatus.FAILED
    if StageStatus.RUNNING in values:
        return JobStatus.RUNNING
    if StageStatus.PENDING in values:
        return JobStatus.QUEUED
    return JobStatus.PARTIAL if has_page_failures else JobStatus.DONE


def version_status_for(job_status: JobStatus) -> VersionStatus:
    return {
        JobStatus.DONE: VersionStatus.DONE,
        JobStatus.PARTIAL: VersionStatus.PARTIAL,
        JobStatus.FAILED: VersionStatus.FAILED,
    }.get(job_status, VersionStatus.PROCESSING)


def retryable_stages(stage_statuses: dict[JobStage, StageStatus]) -> list[JobStage]:
    """Stages a caller may restart from: the failed one and everything after."""
    for index, stage in enumerate(STAGE_ORDER):
        if stage_statuses.get(stage) is StageStatus.FAILED:
            return list(STAGE_ORDER[index:])
    return []
