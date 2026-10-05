"""External schemas and evidence-bearing candidates for M2b contract tests."""

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256

from docgrain_api.entity_service import EntityBatch, EntityCandidate
from docgrain_domain.canonical.entities import RegisteredSchema
from docgrain_domain.canonical.entity_fields import leaf_pointers
from docgrain_domain.canonical.identity import canonical_json_bytes
from docgrain_domain.canonical.models import (
    Annotation,
    DomainSchemaRef,
    EntityReviewEvent,
    Producer,
)


def registered_schema(workspace_id="workspace-test", schema_id="hotel.room.v1", version="1", document=None):
    document = document or {"type": "object", "additionalProperties": False,
                            "properties": {"name": {"type": "string", "minLength": 1},
                                           "capacity": {"type": "integer", "minimum": 1}},
                            "required": ["name", "capacity"]}
    return RegisteredSchema(workspace_id=workspace_id, reference=DomainSchemaRef(
        id=schema_id, version=version, content_sha256=sha256(canonical_json_bytes(document)).hexdigest()),
        document=document)


def entity_batch(snapshot, schema=None, data=None, key="test-key"):
    schema = schema or registered_schema(snapshot.workspace_id)
    data = data if data is not None else {"name": "Synthetic entity", "capacity": 3}
    annotation = deepcopy(snapshot.structure[-1].annotation.model_dump(mode="json"))
    annotation["provenance"]["producer_id"] = "producer-test-entity"
    annotation["review_status"] = "proposed"
    return EntityBatch(schema_ref=schema.reference,
                       producer=Producer(id="producer-test-entity", name="test-external-input", version="1"),
                       entities=[EntityCandidate(identity_key=key, type="external-test-type", label=key, data=data,
                                                   annotation=Annotation.model_validate(annotation),
                                                   field_annotations={path: Annotation.model_validate(annotation)
                                                                      for path in leaf_pointers(data)})])


def decision(from_status, to_status, decision_id=None):
    return EntityReviewEvent(decision_id=decision_id or f"decision-{to_status}",
                             from_status=from_status, to_status=to_status, reviewer_id="test-reviewer",
                             reason="Synthetic contract decision", occurred_at=datetime(2026, 10, 1, tzinfo=UTC))
