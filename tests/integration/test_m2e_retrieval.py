"""Pinned PostgreSQL reads, exact structured data and consumer HTTP contracts."""

import pytest
from docgrain_api.index_repository import IndexRepository
from docgrain_api.main import app
from docgrain_api.retrieval_repository import RetrievalRepository
from docgrain_api.routers import retrieval as routes
from docgrain_api.settings import get_settings
from docgrain_domain.canonical.retrieval import RetrievalQuery, retrieve
from docgrain_worker.index_lifecycle import refresh_index
from fastapi.testclient import TestClient

from tests.fixtures.incremental import FixtureEmbedder, index_spec, revised
from tests.integration import test_m2a_repository as m2a_fixtures
from tests.integration.test_m2b_repository import accepted
from tests.unit.test_m2c_chunking import rich_snapshot

lifecycle_store = m2a_fixtures.lifecycle_store


def test_structured_without_vector_db_filtered_json_and_evidence(lifecycle_store, monkeypatch):
    source, connect, schema = lifecycle_store
    *_before, snapshot = accepted(source)
    repository = RetrievalRepository(connect, schema)
    request = RetrievalQuery(workspace_id=snapshot.workspace_id, document_ids=[snapshot.document_id], mode="structured",
                             schemas=[{"id": "hotel.room.v1", "version": "1"}],
                             predicates=[{"path": "/capacity", "operator": "gte", "value": 3}])
    # If a query accidentally runs the write-time path, fail immediately.
    import docgrain_worker.index_lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, "refresh_index", lambda *_a, **_kw: pytest.fail("ordinary embedding on query path"))
    result = retrieve(repository.read_views(request), request)
    assert result.hits[0].data == snapshot.entities[0].data and result.hits[0].evidence
    assert result.hits[0].schema_version == "1" and not result.pinned_generations
    request.predicates[0].value = 4
    assert not retrieve(repository.read_views(request), request).hits
    request.workspace_id = "other"
    with pytest.raises(LookupError, match="workspace"):
        repository.read_views(request)


def test_generation_pinned_after_head_switch_deleted_data_not_mixed(lifecycle_store):
    source, connect, schema = lifecycle_store
    old = rich_snapshot()
    source.append(old, expected_latest_revision_id=None)
    index = IndexRepository(connect, schema)
    first, _ = refresh_index(index, old.knowledge_revision.id, index_spec(), FixtureEmbedder(), expected_generation_id=None)
    repository = RetrievalRepository(connect, schema)
    request = RetrievalQuery(workspace_id=old.workspace_id, document_ids=[old.document_id], mode="lexical", text="Beta")
    pinned = repository.read_views(request)
    def remove(value):
        value["structure"] = [value["structure"][0]]
        value["structure"][0]["children"] = []
    newer = revised(old, remove)
    source.append(newer, expected_latest_revision_id=old.knowledge_revision.id)
    # Until index is ready, lexical still uses old canonical/index together.
    assert retrieve(repository.read_views(request), request).pinned_generations[old.document_id] == first.revision.id
    second, _ = refresh_index(index, newer.knowledge_revision.id, index_spec(), FixtureEmbedder(), expected_generation_id=first.revision.id)
    assert retrieve(pinned, request).hits and not retrieve(repository.read_views(request), request).hits
    assert retrieve(repository.read_views(request), request).pinned_revisions[old.document_id] == newer.knowledge_revision.id
    assert second.entries == []


def test_http_direct_lexical_capability_errors_and_no_runtime_fake_data(lifecycle_store, monkeypatch):
    source, connect, schema = lifecycle_store
    snapshot = rich_snapshot()
    source.append(snapshot, expected_latest_revision_id=None)
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(routes, "lifecycle_repository", lambda: source)
    client = TestClient(app)
    body = {"workspace_id": snapshot.workspace_id, "document_ids": [snapshot.document_id], "mode": "direct"}
    response = client.post("/v1/knowledge/retrieve", json=body)
    assert response.status_code == 200 and response.json()["hits"][0]["evidence"]
    assert response.json()["timings_ms"]["embed"] == 0
    assert client.post("/v1/knowledge/retrieve", json={**body, "direct_max_chars": 1}).status_code == 409
    lexical = {**body, "mode": "lexical", "text": "Beta"}
    assert client.post("/v1/knowledge/retrieve", json=lexical).status_code == 409
    index = IndexRepository(connect, schema)
    refresh_index(index, snapshot.knowledge_revision.id, index_spec(), FixtureEmbedder(), expected_generation_id=None)
    assert client.post("/v1/knowledge/retrieve", json=lexical).status_code == 200
    assert client.post("/v1/knowledge/retrieve", json={**body, "workspace_id": "other"}).status_code == 404
    assert client.post("/v1/knowledge/retrieve", json={**body, "mode": "vector"}).status_code == 422
