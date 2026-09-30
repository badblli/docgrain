"""External schema/entity lifecycle against isolated PostgreSQL and real XLSX."""

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from docgrain_api.canonical_repository import CanonicalConflict
from docgrain_api.entity_service import (
    EntityBatch,
    entity_projection,
    publish_entities,
    publish_review,
)
from docgrain_api.main import app
from docgrain_api.routers import entities as entity_routes
from docgrain_api.settings import get_settings
from docgrain_api.table_entities import ColumnBinding, table_candidates
from docgrain_domain.canonical.lineage import DerivedManifest, ObjectRef
from docgrain_domain.canonical.models import CanonicalKnowledgeSnapshot, Producer
from docgrain_worker.canonical_writer import persist_structural
from fastapi.testclient import TestClient
from psycopg import sql

from tests.fixtures.entities import decision, entity_batch, registered_schema
from tests.fixtures.lifecycle import mapped_snapshot
from tests.integration import test_m2a_repository as m2a_fixtures

lifecycle_store = m2a_fixtures.lifecycle_store
real_corpus = m2a_fixtures.real_corpus


def seed(repository, data=None):
    _, parsed, source, spec = mapped_snapshot()
    base, _ = persist_structural(repository, parsed, source, spec=spec)
    schema = registered_schema(base.workspace_id)
    repository.register_schema(schema)
    batch = entity_batch(base, schema, data)
    extracted, _ = publish_entities(repository, base, batch)
    return base, extracted, batch


def accepted(repository):
    base, extracted, _batch = seed(repository)
    identity = extracted.entities[0].id
    pending, _ = publish_review(repository, extracted, identity, decision("extracted", "needs_review"))
    result, _ = publish_review(repository, pending, identity, decision("needs_review", "accepted"))
    return base, extracted, pending, result


def test_schema_registry_immutability_scope_and_replay(lifecycle_store):
    repository, connect, namespace = lifecycle_store
    schema = registered_schema()
    assert repository.register_schema(schema)
    assert not repository.register_schema(schema)
    assert repository.get_schema(schema.workspace_id, schema.reference.id, "1") == schema
    assert repository.get_schema("other", schema.reference.id, "1") is None
    changed = registered_schema(document={"type": "object", "title": "new"})
    with pytest.raises(CanonicalConflict, match="different immutable content"):
        repository.register_schema(changed)
    assert repository.register_schema(registered_schema(version="2", document=changed.document))
    assert repository.register_schema(registered_schema(workspace_id="other"))
    with pytest.raises(psycopg.errors.RaiseException), connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("UPDATE {} SET version='modified'").format(sql.Identifier(namespace, "domain_schema_registry")))


def test_entity_replay_schema_provenance_and_identity(lifecycle_store):
    repository, _, _ = lifecycle_store
    base, extracted, batch = seed(repository)
    replay, inserted = publish_entities(repository, base, batch)
    assert not inserted and replay == extracted
    assert extracted.schema_version == "0.4.0" and extracted.entities[0].validation.status == "valid"
    assert base.source_version == extracted.source_version and base.structure == extracted.structure
    assert repository.get_snapshot(base.knowledge_revision.id) == base
    second_schema = registered_schema(schema_id="catalog.product.v1", document={"type": "object"})
    repository.register_schema(second_schema)
    second_batch = entity_batch(extracted, second_schema, {"sku": "P-01"})
    combined, _ = publish_entities(repository, extracted, second_batch)
    assert len(combined.entities) == 2 and combined.entities[0].id != combined.entities[1].id
    wrong = copy.deepcopy(batch.model_dump(mode="json"))
    wrong["schema_ref"]["version"] = "99"
    with pytest.raises(ValueError, match="not registered"):
        publish_entities(repository, combined, EntityBatch.model_validate(wrong))
    wrong = copy.deepcopy(second_batch.model_dump(mode="json"))
    wrong["entities"][0]["field_annotations"]["/sku"]["provenance"]["evidence_ids"] = ["unknown-evidence"]
    with pytest.raises(ValueError, match="dangling evidence"):
        publish_entities(repository, combined, EntityBatch.model_validate(wrong))
    correction = entity_batch(combined, data={"name": "Corrected", "capacity": 4})
    corrected, _ = publish_entities(repository, combined, correction)
    assert next(e for e in corrected.entities if e.schema_id == batch.schema_ref.id).id == combined.entities[0].id


def test_review_replay_approval_guard_and_concurrent_decisions(lifecycle_store):
    repository, _, _ = lifecycle_store
    base, extracted, _batch = seed(repository)
    identity = extracted.entities[0].id
    with pytest.raises(CanonicalConflict, match="awaiting acceptance"):
        repository.approve(base.document_id, base.workspace_id, extracted.knowledge_revision.id,
                           expected_approved_revision_id=None)
    event = decision("extracted", "needs_review")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish_review(repository, extracted, identity, event)[1], range(2)))
    assert sorted(results) == [False, True]
    head = repository.get_snapshot(repository.get_heads(base.document_id)[0])
    def vote(status):
        try:
            return publish_review(repository, head, identity, decision("needs_review", status))[1]
        except CanonicalConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(vote, ["accepted", "rejected"])) == [False, True]
    final = repository.get_snapshot(repository.get_heads(base.document_id)[0])
    assert final.entities[0].data == extracted.entities[0].data
    assert repository.get_snapshot(extracted.knowledge_revision.id).entities[0].review_status == "extracted"


def test_invalid_data_cannot_be_accepted_or_forge_validation(lifecycle_store):
    repository, _, _ = lifecycle_store
    _, extracted, _ = seed(repository, {"name": "Synthetic", "capacity": "invalid"})
    identity = extracted.entities[0].id
    pending, _ = publish_review(repository, extracted, identity, decision("extracted", "needs_review"))
    with pytest.raises(ValueError, match="schema-valid"):
        publish_review(repository, pending, identity, decision("needs_review", "accepted"))
    forged = pending.model_dump(mode="json")
    entity = forged["entities"][0]
    entity["validation"] = {"status": "valid", "errors": []}
    entity["review_status"] = "accepted"
    entity["annotation"]["review_status"] = "approved"
    entity["review_events"].append(decision("needs_review", "accepted").model_dump(mode="json"))
    with pytest.raises(CanonicalConflict, match="validation differs"):
        repository.append(CanonicalKnowledgeSnapshot.model_validate(forged),
                          expected_latest_revision_id=extracted.knowledge_revision.id)
    rejected, _ = publish_review(repository, pending, identity, decision("needs_review", "rejected"))
    assert rejected.entities[0].validation.status == "invalid"


def test_separate_projection_verified_payload_lineage_and_approval(lifecycle_store):
    repository, _, _ = lifecycle_store
    base, extracted, _pending, final = accepted(repository)
    identity = final.entities[0].id
    with pytest.raises(CanonicalConflict, match="accepted"):
        entity_projection(extracted, identity)
    original = copy.deepcopy(final.model_dump(mode="json"))
    projection = entity_projection(final, identity)
    assert repository.append_derived(projection)
    assert not repository.append_derived(projection)
    assert repository.get_derivation(projection.revision.id) == projection
    assert json.loads(projection.projections[0].text) == final.entities[0].data
    assert repository.get_snapshot(final.knowledge_revision.id).model_dump(mode="json") == original
    graph = repository.get_lineage(final.knowledge_revision.id)
    ref = projection.objects[0]
    assert ObjectRef(kind="canonical", object_id=identity, revision_id=final.knowledge_revision.id) in graph.trace(ref, "upstream").objects
    tampered = projection.model_dump(mode="json")
    tampered["projections"][0]["text"] = '{"capacity":999}'
    tampered["projections"][0]["content_sha256"] = hashlib.sha256(b'{"capacity":999}').hexdigest()
    with pytest.raises(CanonicalConflict, match="differs from canonical"):
        repository.append_derived(DerivedManifest.model_validate(tampered))
    repository.approve(base.document_id, base.workspace_id, final.knowledge_revision.id,
                       expected_approved_revision_id=None)
    assert repository.get_heads(base.document_id)[1] == final.knowledge_revision.id
    from docgrain_domain.canonical.schema import (
        generated_core_schema,
        generated_lineage_schema_text,
    )
    from jsonschema import Draft202012Validator
    Draft202012Validator(generated_core_schema("0.4.0")).validate(final.model_dump(mode="json"))
    Draft202012Validator(json.loads(generated_lineage_schema_text("0.2.0"))).validate(projection.model_dump(mode="json"))


def test_live_api_register_publish_review_project(lifecycle_store, monkeypatch):
    repository, _, _ = lifecycle_store
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(entity_routes, "lifecycle_repository", lambda: repository)
    client = TestClient(app)
    _, parsed, source, spec = mapped_snapshot()
    base, _ = persist_structural(repository, parsed, source, spec=spec)
    schema = registered_schema()
    response = client.post("/v1/schemas", json=schema.model_dump(mode="json"))
    assert response.status_code == 200 and response.json()["inserted"]
    assert client.get(f"/v1/schemas/{schema.reference.id}/versions/1", params={"workspace_id": "wrong"}).status_code == 404
    response = client.post(f"/v1/knowledge/revisions/{base.knowledge_revision.id}/entities", json=entity_batch(base).model_dump(mode="json"))
    assert response.status_code == 200
    current = CanonicalKnowledgeSnapshot.model_validate(response.json())
    identity = current.entities[0].id
    for before, after in (("extracted", "needs_review"), ("needs_review", "accepted")):
        response = client.post(f"/v1/knowledge/revisions/{current.knowledge_revision.id}/entities/{identity}/reviews",
                               json=decision(before, after).model_dump(mode="json"))
        assert response.status_code == 200
        current = CanonicalKnowledgeSnapshot.model_validate(response.json())
    path = f"/v1/knowledge/revisions/{current.knowledge_revision.id}/entities/{identity}/projection"
    response = client.post(path)
    assert response.status_code == 200 and response.json()["inserted"]
    assert client.post(path).json()["inserted"] is False
    derived = response.json()["manifest"]["revision"]["id"]
    assert client.get(f"/v1/knowledge/derivations/{derived}").status_code == 200


def test_real_xlsx_candidate_mapping_preserves_cell_evidence(lifecycle_store, real_corpus):
    pytest.importorskip("docling")
    from datetime import UTC, datetime

    from docgrain_domain.canonical import SourceVersion
    from docgrain_domain.source_format import SourceFormat
    from docgrain_worker.structural import DocumentParser, VerifiedSource

    repository, _, _ = lifecycle_store
    path = real_corpus["xlsx"]
    raw = path.read_bytes()
    parsed = DocumentParser().parse(VerifiedSource(path, hashlib.sha256(raw).hexdigest(), len(raw)), SourceFormat.XLSX)
    for item in parsed.items:
        if item.asset_bytes:
            item.asset_path = "fixture://asset/" + hashlib.sha256(item.asset_bytes).hexdigest()
    source = SourceVersion(id="pending", document_id="document-test", workspace_id="workspace-test",
                           content_sha256=hashlib.sha256(raw).hexdigest(), storage_uri="fixture://xlsx",
                           storage_version="v1", byte_size=len(raw), mime_type="application/xlsx", filename=path.name,
                           recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    base, _ = persist_structural(repository, parsed, source)
    table = next(node for node in base.structure if node.kind == "table" and node.rows[0][0].value == "Name")
    # Map the scalar source row; formula and empty rows are explicitly excluded from this example.
    table = table.model_copy(update={"rows": table.rows[:2]})
    view = base.model_copy(update={"structure": [table if node.id == table.id else node for node in base.structure]})
    producer = Producer(id="producer-table-mapping", name="canonical-table-mapping", version="1")
    candidates = table_candidates(view, table.id, bindings={"name": ColumnBinding(0), "capacity": ColumnBinding(1)},
                                  identity_field="name", entity_type="external-test", producer=producer)
    schema = registered_schema()
    repository.register_schema(schema)
    result, _ = publish_entities(repository, base, EntityBatch(schema_ref=schema.reference, producer=producer, entities=candidates))
    entity = result.entities[0]
    assert entity.data == {"name": "A", "capacity": 2} and entity.validation.status == "valid"
    evidence = {item.id: item.locator for item in base.evidence}
    for path, address in (("/name", "A2"), ("/capacity", "B2")):
        ids = entity.field_annotations[path].provenance.evidence_ids
        assert any(evidence[ref].kind == "spreadsheet_range" and evidence[ref].a1_range == address for ref in ids)
