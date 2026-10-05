"""Canonical lifecycle manifests and revision-scoped lineage queries."""

from typing import Literal

import psycopg
from docgrain_domain.canonical.lineage import DerivedManifest, LineageTrace, ObjectKind, ObjectRef
from fastapi import APIRouter, HTTPException, Query

from ..canonical_repository import CanonicalConflict, CanonicalRepository
from ..settings import get_settings

router = APIRouter(prefix="/v1/knowledge/revisions", tags=["knowledge"])


def lifecycle_repository() -> CanonicalRepository:
    settings = get_settings()
    if settings.use_fixtures or not settings.canonical_persistence_enabled:
        raise HTTPException(404, "canonical lifecycle is unavailable in this mode")
    return CanonicalRepository(lambda: psycopg.connect(
        settings.database_url.replace("postgresql+psycopg://", "postgresql://")))


@router.get("/{revision_id}/lineage", response_model=LineageTrace)
def trace_lineage(revision_id: str, kind: ObjectKind, object_id: str,
                  object_revision_id: str,
                  direction: Literal["upstream", "downstream"] = "upstream",
                  max_depth: int = Query(16, ge=1, le=32),
                  max_objects: int = Query(1000, ge=1, le=2000)) -> LineageTrace:
    graph = lifecycle_repository().get_lineage(revision_id)
    if graph is None:
        raise HTTPException(404, "canonical revision not found")
    try:
        return graph.trace(ObjectRef(kind=kind, revision_id=object_revision_id, object_id=object_id),
                           direction, max_depth=max_depth, max_objects=max_objects)
    except KeyError as exc:
        raise HTTPException(404, "lineage occurrence not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{revision_id}/derivations")
def publish_derivation(revision_id: str, manifest: DerivedManifest) -> dict[str, str | bool]:
    if get_settings().use_fixtures:
        raise HTTPException(409, "demo mode is read-only")
    if manifest.revision.processing_revision_id != revision_id:
        raise HTTPException(422, "manifest processing revision differs from request path")
    repository = lifecycle_repository()
    if repository.get_snapshot(revision_id) is None:
        raise HTTPException(404, "canonical revision not found")
    try:
        inserted = repository.append_derived(manifest)
    except CanonicalConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"revision_id": manifest.revision.id, "inserted": inserted}
