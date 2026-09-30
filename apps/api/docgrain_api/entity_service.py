"""Schema-bound entity publication, immutable review revisions and derived JSON text."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256

from docgrain_domain.canonical.entities import RegisteredSchema, review_entity, validate_entity_data
from docgrain_domain.canonical.lifecycle import (
    DerivedRevision,
    digest,
    entity_id,
    processing_revision_id,
    scoped_id,
)
from docgrain_domain.canonical.lineage import (
    DerivedManifest,
    LineageEdge,
    ObjectRef,
    ProjectionArtifact,
)
from docgrain_domain.canonical.locations import StrictModel
from docgrain_domain.canonical.models import (
    Annotation,
    CanonicalKnowledgeSnapshot,
    DomainSchemaRef,
    EntityReviewEvent,
    Producer,
    SchemaEntity,
)
from pydantic import Field, JsonValue

from .canonical_repository import CanonicalConflict, CanonicalRepository


class EntityCandidate(StrictModel):
    identity_key: str = Field(min_length=1)
    type: str = Field(min_length=1)
    label: str
    data: dict[str, JsonValue]
    annotation: Annotation
    field_annotations: dict[str, Annotation]


class EntityBatch(StrictModel):
    schema_ref: DomainSchemaRef
    producer: Producer
    entities: list[EntityCandidate] = Field(min_length=1)


def _revision(base: CanonicalKnowledgeSnapshot, operation: dict, *, entities=None, schemas=None, producer=None):
    if base.knowledge_revision.processing is None:
        raise ValueError("entity publication requires an M2a processing revision; reprocess legacy source first")
    payload = deepcopy(base.model_dump(mode="json"))
    spec = base.knowledge_revision.processing.model_dump(mode="json")
    spec["schema_version"] = "0.4.0"
    spec["options"]["entity_operation"] = {"base_revision_id": base.knowledge_revision.id,
                                           "contract_version": "m2b-1", "input_digest": digest(operation)}
    from docgrain_domain.canonical.lifecycle import ProcessingSpec
    processing = ProcessingSpec.model_validate(spec)
    revision = payload["knowledge_revision"]
    revision["id"] = processing_revision_id(base.source_version.id, processing)
    revision["parent_revision_id"] = base.knowledge_revision.id
    revision["processing"] = processing.model_dump(mode="json")
    if producer is not None:
        old = next((p for p in revision["producers"] if p["id"] == producer.id), None)
        if old and (old["name"], old["version"]) != (producer.name, producer.version):
            raise ValueError("entity producer ID conflicts with the upstream producer")
        if old is None:
            revision["producers"].append(producer.model_dump(mode="json"))
    for declared in revision["producers"]:
        declared["configuration_digest"] = processing.digest
    payload["schema_version"] = "0.4.0"
    if entities is not None:
        payload["entities"] = [item.model_dump(mode="json") for item in entities]
    if schemas is not None:
        payload["domain_schemas"] = [item.model_dump(mode="json") for item in schemas]
    return CanonicalKnowledgeSnapshot.model_validate(payload)


def publish_entities(repository: CanonicalRepository, base: CanonicalKnowledgeSnapshot,
                     batch: EntityBatch) -> tuple[CanonicalKnowledgeSnapshot, bool]:
    batch = EntityBatch.model_validate(batch.model_dump(mode="json"))
    schema = repository.get_schema(base.workspace_id, batch.schema_ref.id, batch.schema_ref.version)
    if schema is None or schema.reference != batch.schema_ref:
        raise ValueError("schema ID/version/checksum is not registered in this workspace")
    schema = RegisteredSchema.model_validate(schema.model_dump(mode="json"))
    schemas = {item.id: item for item in base.domain_schemas}
    existing_ref = schemas.get(schema.reference.id)
    if existing_ref is not None and existing_ref != schema.reference:
        raise ValueError("snapshot cannot mix different versions/checksums of one logical schema")
    schemas[schema.reference.id] = schema.reference
    new_entities = []
    for candidate in batch.entities:
        annotations = [candidate.annotation, *candidate.field_annotations.values()]
        if any(annotation.provenance.producer_id != batch.producer.id for annotation in annotations):
            raise ValueError("entity/field producer must match batch producer")
        annotation = candidate.annotation.model_copy(update={"review_status": "proposed"})
        new_entities.append(SchemaEntity(
            id=entity_id(base.document_id, schema.reference.id, candidate.identity_key),
            schema_id=schema.reference.id, schema_version=schema.reference.version,
            annotation=annotation, validation=validate_entity_data(candidate.data, schema),
            **candidate.model_dump(exclude={"annotation", "field_annotations"}),
            field_annotations=candidate.field_annotations,
        ))
    new_ids = {entity.id for entity in new_entities}
    if len(new_ids) != len(new_entities):
        raise ValueError("duplicate entity identity in batch")
    # An explicit new extraction replaces occurrences with the same logical identity only.
    entities = [entity for entity in base.entities if entity.id not in new_ids] + new_entities
    snapshot = _revision(base, {"batch": batch.model_dump(mode="json")}, entities=entities,
                         schemas=list(schemas.values()), producer=batch.producer)
    inserted = repository.append(snapshot, expected_latest_revision_id=base.knowledge_revision.id)
    return snapshot, inserted


def publish_review(repository: CanonicalRepository, base: CanonicalKnowledgeSnapshot, entity_identity: str,
                   event: EntityReviewEvent) -> tuple[CanonicalKnowledgeSnapshot, bool]:
    entity = next((item for item in base.entities if item.id == entity_identity), None)
    if not isinstance(entity, SchemaEntity):
        raise KeyError("schema entity not found")
    updated = review_entity(entity, event)
    entities = [updated if item.id == entity_identity else item for item in base.entities]
    snapshot = _revision(base, {"entity_id": entity_identity, "review": event.model_dump(mode="json")}, entities=entities)
    inserted = repository.append(snapshot, expected_latest_revision_id=base.knowledge_revision.id)
    return snapshot, inserted


def entity_projection(snapshot: CanonicalKnowledgeSnapshot, entity_identity: str) -> DerivedManifest:
    entity = next((item for item in snapshot.entities if item.id == entity_identity), None)
    if not isinstance(entity, SchemaEntity):
        raise KeyError("schema entity not found")
    if entity.review_status != "accepted" or entity.validation.status != "valid":
        raise CanonicalConflict("retrieval projection requires an accepted schema-valid entity")
    text = json.dumps(entity.data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    processing_id = snapshot.knowledge_revision.id
    upstream = ObjectRef(kind="canonical", revision_id=processing_id, object_id=entity.id)
    revision = DerivedRevision.create(workspace_id=snapshot.workspace_id, document_id=snapshot.document_id,
                                       processing_revision_id=processing_id, stage="projection",
                                       upstream_revision_ids=(processing_id,), strategy="entity-json", strategy_version="1",
                                       configuration={"entity_id": entity.id})
    target = ObjectRef(kind="projection", revision_id=revision.id,
                       object_id=scoped_id("projection", [entity.id, "entity-json", "1"]))
    return DerivedManifest(schema_version="0.2.0", revision=revision, objects=[target],
                            edges=[LineageEdge(upstream=upstream, downstream=target)],
                            projections=[ProjectionArtifact(object_ref=target, text=text,
                                                            content_sha256=sha256(text.encode()).hexdigest())])
