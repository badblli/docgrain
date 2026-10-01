"""Explicit canonical chunk derivation; no legacy fixture or embedding fallback."""

from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunks
from docgrain_domain.canonical.lineage import ChunkPayload, DerivedManifest
from fastapi import APIRouter, HTTPException

from ..canonical_repository import CanonicalConflict
from ..settings import get_settings
from .lineage import lifecycle_repository

router = APIRouter(prefix="/v1/knowledge", tags=["canonical-chunks"])


def _chunk_revision(repository, derived_revision_id):
    manifest = repository.get_derivation(derived_revision_id)
    if manifest is None or manifest.revision.stage != "chunking" or not manifest.chunks:
        raise HTTPException(404, "generated chunk revision not found")
    return manifest


@router.post("/revisions/{revision_id}/chunks")
def publish_chunks(revision_id: str, spec: ChunkingSpec):
    if get_settings().use_fixtures:
        raise HTTPException(409, "demo mode is read-only")
    repository = lifecycle_repository()
    snapshot = repository.get_snapshot(revision_id)
    if snapshot is None:
        raise HTTPException(404, "canonical revision not found")
    try:
        manifest = derive_chunks(snapshot, spec)
        inserted = repository.append_derived(manifest)
    except CanonicalConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"manifest": manifest, "inserted": inserted}


@router.get("/revisions/{revision_id}/chunks", response_model=DerivedManifest)
def get_chunks(revision_id: str, chunk_revision_id: str):
    repository = lifecycle_repository()
    if repository.get_snapshot(revision_id) is None:
        raise HTTPException(404, "canonical revision not found")
    manifest = _chunk_revision(repository, chunk_revision_id)
    if manifest.revision.processing_revision_id != revision_id:
        raise HTTPException(404, "chunk revision does not belong to this canonical revision")
    return manifest


@router.get("/derivations/{derived_revision_id}/chunks/{chunk_id}", response_model=ChunkPayload)
def get_chunk(derived_revision_id: str, chunk_id: str):
    manifest = _chunk_revision(lifecycle_repository(), derived_revision_id)
    chunk = next((item for item in manifest.chunks if item.object_ref.object_id == chunk_id), None)
    if chunk is None:
        raise HTTPException(404, "chunk not found in this derived revision")
    return chunk
