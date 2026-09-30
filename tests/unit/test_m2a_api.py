"""HTTP contract checks for revision-scoped lineage and derived publication."""

from docgrain_api.canonical_repository import CanonicalConflict
from docgrain_api.main import app
from docgrain_api.routers import lineage
from docgrain_domain.canonical.lineage import LineageGraph
from fastapi.testclient import TestClient

from tests.fixtures.lifecycle import derived_chain, mapped_snapshot

client = TestClient(app)


def test_demo_never_fabricates_lineage_or_accepts_writes():
    snapshot, *_ = mapped_snapshot()
    _, manifests = derived_chain(snapshot)
    path = f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}"
    assert client.get(path + "/lineage", params={"kind": "canonical", "object_id": "x",
                                               "object_revision_id": "y"}).status_code == 404
    assert client.post(path + "/derivations", json=manifests[0].model_dump(mode="json")).status_code == 409


def test_live_trace_occurrence_validation_and_publication(monkeypatch):
    from docgrain_api.settings import get_settings
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    snapshot, *_ = mapped_snapshot()
    canonical, manifests = derived_chain(snapshot)
    graph = LineageGraph(snapshot)
    for manifest in manifests:
        graph.extend(manifest)
    class Store:
        def get_lineage(self, revision):
            return graph if revision == snapshot.knowledge_revision.id else None
        def get_snapshot(self, revision):
            return snapshot if revision == snapshot.knowledge_revision.id else None
        def append_derived(self, manifest):
            return False
    monkeypatch.setattr(lineage, "lifecycle_repository", Store)
    path = f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}"
    params = {"kind": "canonical", "object_id": canonical.object_id,
              "object_revision_id": canonical.revision_id, "direction": "downstream"}
    response = client.get(path + "/lineage", params=params)
    assert response.status_code == 200
    assert {obj["kind"] for obj in response.json()["objects"]} == {"canonical", "chunk", "embedding", "index"}
    assert client.get(path + "/lineage", params={**params, "object_revision_id": "wrong"}).status_code == 404
    assert client.get(path + "/lineage", params={**params, "max_depth": 0}).status_code == 422
    assert client.get(path + "/lineage", params={**params, "max_objects": 2}).status_code == 422
    assert client.get("/v1/knowledge/revisions/missing/lineage", params=params).status_code == 404
    payload = manifests[0].model_dump(mode="json")
    response = client.post(path + "/derivations", json=payload)
    assert response.status_code == 200 and response.json()["inserted"] is False
    assert client.post("/v1/knowledge/revisions/wrong/derivations", json=payload).status_code == 422
    def conflict(self, manifest):
        raise CanonicalConflict("immutable conflict")
    monkeypatch.setattr(Store, "append_derived", conflict)
    assert client.post(path + "/derivations", json=payload).status_code == 409
