"""Cache mutation isolation and capacity gates."""

from docgrain_api.retrieval_cache import RevisionCache

from tests.fixtures.retrieval import view


def test_cache_cannot_be_mutated_by_callers_and_is_byte_bound():
    fixture = view()
    cache = RevisionCache(max_bytes=len(fixture.model_dump_json().encode()) + 10)
    cache.put("a", fixture)
    received = cache.get("a")
    received.context = "malicious mutation"
    assert cache.get("a").context == fixture.context
    cache.put("b", fixture)
    assert cache.get("a") is None and cache.get("b")
    cache.clear()
    assert cache.get("b") is None
    RevisionCache(max_bytes=1).put("c", fixture)
