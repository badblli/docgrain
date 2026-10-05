"""Warm caches recheck current heads and scope rather than returning stale documents."""

from docgrain_api.retrieval_cache import RevisionCache
from docgrain_api.retrieval_repository import RetrievalRepository
from docgrain_domain.canonical.retrieval import RetrievalQuery

from tests.fixtures.incremental import revised
from tests.integration import test_m2a_repository as m2a_fixtures
from tests.unit.test_m2c_chunking import rich_snapshot

lifecycle_store = m2a_fixtures.lifecycle_store


def test_warm_context_cache_does_not_hide_head_changes(lifecycle_store):
    source, connect, schema = lifecycle_store
    old = rich_snapshot()
    source.append(old, expected_latest_revision_id=None)
    repository = RetrievalRepository(connect, schema, cache=RevisionCache())
    query = RetrievalQuery(workspace_id=old.workspace_id, document_ids=[old.document_id], mode="direct")
    before = repository.read_views(query)[0]
    assert repository.read_views(query)[0] == before
    newer = revised(old, lambda value: value["structure"][0].update(title="New context"))
    source.append(newer, expected_latest_revision_id=old.knowledge_revision.id)
    assert repository.read_views(query)[0].snapshot == newer
    assert before.snapshot == old
