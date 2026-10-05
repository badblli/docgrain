"""Read-only diff, chunk planning and active index inspection; no model dispatch."""

from docgrain_domain.canonical.chunking import ChunkingSpec
from docgrain_domain.canonical.incremental import (
    canonical_diff,
    invalidated_descendants,
    plan_chunks,
)
from docgrain_domain.canonical.locations import StrictModel
from fastapi import APIRouter, HTTPException
from pydantic import Field

from ..index_repository import IndexRepository
from .lineage import lifecycle_repository

router = APIRouter(prefix="/v1/knowledge", tags=["canonical-lifecycle"])


class DiffRequest(StrictModel):
    from_revision_id: str = Field(min_length=1)


class PlanRequest(DiffRequest):
    chunking: ChunkingSpec = Field(default_factory=ChunkingSpec)
    previous_chunking: ChunkingSpec | None = None


def _pair(repository, revision_id, from_revision_id):
    before, after = repository.get_snapshot(from_revision_id), repository.get_snapshot(revision_id)
    if before is None or after is None:
        raise HTTPException(404, "canonical revision not found")
    if (before.workspace_id, before.document_id) != (after.workspace_id, after.document_id):
        raise HTTPException(422, "canonical diff workspace/document scope mismatch")
    return before, after


@router.post("/revisions/{revision_id}/diff")
def diff_revision(revision_id: str, request: DiffRequest):
    repository = lifecycle_repository()
    before, after = _pair(repository, revision_id, request.from_revision_id)
    diff = canonical_diff(before, after)
    return {"diff": diff, "invalidated_candidates": invalidated_descendants(diff, repository.get_lineage(before.knowledge_revision.id))}


@router.post("/revisions/{revision_id}/index-plan")
def index_plan(revision_id: str, request: PlanRequest):
    repository = lifecycle_repository()
    before, after = _pair(repository, revision_id, request.from_revision_id)
    try:
        return plan_chunks(before, after, request.chunking, previous_spec=request.previous_chunking)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/documents/{document_id}/indexes/{index_name}")
def active_index(document_id: str, index_name: str, workspace_id: str):
    repository = lifecycle_repository()
    index = IndexRepository(repository._connect, repository._schema)
    result = index.get_active(workspace_id, document_id, index_name)
    if result is None:
        raise HTTPException(404, "active index generation not found")
    return result
