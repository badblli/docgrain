"""External schema registry, entity candidates/review and separate projections."""

from docgrain_domain.canonical.entities import RegisteredSchema
from docgrain_domain.canonical.models import (
    CanonicalKnowledgeSnapshot,
    EntityReviewEvent,
    SchemaEntity,
)
from fastapi import APIRouter, HTTPException

from ..canonical_repository import CanonicalConflict
from ..entity_service import EntityBatch, entity_projection, publish_entities, publish_review
from ..settings import get_settings
from .lineage import lifecycle_repository

router = APIRouter(prefix="/v1", tags=["entities"])


def _write_repository():
    if get_settings().use_fixtures:
        raise HTTPException(409, "demo mode is read-only")
    return lifecycle_repository()


def _base(repository, revision_id):
    snapshot = repository.get_snapshot(revision_id)
    if snapshot is None:
        raise HTTPException(404, "canonical revision not found")
    return snapshot


@router.post("/schemas")
def register_schema(schema: RegisteredSchema):
    try:
        inserted = _write_repository().register_schema(schema)
    except CanonicalConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"schema_ref": schema.reference, "inserted": inserted}


@router.get("/schemas/{schema_id}/versions/{version}", response_model=RegisteredSchema)
def get_schema(schema_id: str, version: str, workspace_id: str):
    schema = lifecycle_repository().get_schema(workspace_id, schema_id, version)
    if schema is None:
        raise HTTPException(404, "schema not found in workspace")
    return schema


@router.get("/knowledge/revisions/{revision_id}/entities", response_model=list[SchemaEntity])
def list_entities(revision_id: str):
    snapshot = _base(lifecycle_repository(), revision_id)
    return [entity for entity in snapshot.entities if isinstance(entity, SchemaEntity)]


@router.post("/knowledge/revisions/{revision_id}/entities", response_model=CanonicalKnowledgeSnapshot)
def extract_entities(revision_id: str, batch: EntityBatch):
    repository = _write_repository()
    try:
        snapshot, _ = publish_entities(repository, _base(repository, revision_id), batch)
        return snapshot
    except CanonicalConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/knowledge/revisions/{revision_id}/entities/{entity_id}/reviews", response_model=CanonicalKnowledgeSnapshot)
def review(revision_id: str, entity_id: str, event: EntityReviewEvent):
    repository = _write_repository()
    try:
        snapshot, _ = publish_review(repository, _base(repository, revision_id), entity_id, event)
        return snapshot
    except KeyError as exc:
        raise HTTPException(404, "schema entity not found") from exc
    except CanonicalConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/knowledge/revisions/{revision_id}/entities/{entity_id}/projection")
def project(revision_id: str, entity_id: str):
    repository = _write_repository()
    try:
        manifest = entity_projection(_base(repository, revision_id), entity_id)
        inserted = repository.append_derived(manifest)
        return {"manifest": manifest, "inserted": inserted}
    except KeyError as exc:
        raise HTTPException(404, "schema entity not found") from exc
    except CanonicalConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/knowledge/derivations/{derived_revision_id}")
def get_projection(derived_revision_id: str):
    manifest = lifecycle_repository().get_derivation(derived_revision_id)
    if manifest is None:
        raise HTTPException(404, "derived revision not found")
    return manifest
