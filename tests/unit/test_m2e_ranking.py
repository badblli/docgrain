"""Executable retrieval contract spike."""

import math

import pytest
from docgrain_domain.canonical.retrieval import (
    CapabilityUnavailable,
    DocumentView,
    FieldPredicate,
    QueryEmbedding,
    RetrievalQuery,
    bm25,
    cosine,
    matches,
    retrieve,
)

from tests.fixtures.retrieval import view


def test_exact_numeric_predicates_do_not_coerce_or_require_embedding():
    query = RetrievalQuery(workspace_id="w", document_ids=["d"], mode="structured",
                           predicates=[FieldPredicate(path="/capacity", operator="gte", value=3)])
    assert matches({"capacity": 4}, query.predicates)
    assert not matches({"capacity": "4"}, query.predicates)
    assert not matches({"capacity": True}, query.predicates)
    assert query.query_embedding is None


def query(mode="lexical", **kwargs):
    return RetrievalQuery(workspace_id="workspace-test", document_ids=["document-test"], mode=mode, **kwargs)


def test_lexical_rank_context_unicode_evidence_and_no_false_confidence():
    fixture = view()
    result = retrieve([fixture], query(text="Beta", limit=1))
    assert len(result.hits) == 1 and "Third paragraph" in result.hits[0].text
    hit = result.hits[0]
    assert hit.score_kind == "bm25" and hit.evidence
    assert {"source", "processing", "canonical", "chunk", "embedding", "index"} == {r.kind for r in hit.lineage}
    assert bm25(["日本語 test", "unrelated"], "日本語")[0] > 0
    assert bm25(["rare rare", "common common common"], "rare")[0] > 0
    assert retrieve([fixture], query(text="missing_needle")).hits == []


def test_vector_configuration_zero_norm_cosine_and_fusion_dedup():
    fixture = view(vector_for=lambda c: [0.0, 1.0] if "Beta" in c.retrieval_text else [1.0, 0.0])
    embedding = QueryEmbedding(spec=fixture.generation.spec.embedding, vector=[0.0, 1.0])
    result = retrieve([fixture], query(mode="vector", query_embedding=embedding, limit=1))
    assert result.hits[0].score == 1 and "Beta" in result.hits[0].text
    fusion = retrieve([fixture], query(mode="hybrid", text="Beta", query_embedding=embedding))
    assert fusion.hits[0].score_kind == "rrf" and set(fusion.hits[0].component_scores) == {"bm25", "cosine"}
    assert len({h.object_ref.key for h in fusion.hits}) == len(fusion.hits)
    assert cosine([0, 0], [1, 0]) is None
    assert math.isclose(cosine([1e200, 1e200], [1e200, 1e200]), 1)
    with pytest.raises(ValueError, match="nonzero"):
        QueryEmbedding(spec=embedding.spec, vector=[0.0, 0.0])
    embedding.spec = embedding.spec.model_copy(update={"version": "other"})
    with pytest.raises(CapabilityUnavailable, match="configuration"):
        retrieve([fixture], query(mode="vector", query_embedding=embedding))


def test_scope_filters_apply_before_scoring_and_unavailable_is_explicit():
    fixture = view()
    assert not retrieve([fixture], query(text="Alpha", source_revision_ids=["other"])).hits
    assert not retrieve([fixture], query(text="Alpha", schemas=[{"id": "other"}])).hits
    foreign = query(text="Alpha")
    foreign.workspace_id = "other"
    assert not retrieve([fixture], foreign).hits
    with pytest.raises(CapabilityUnavailable, match="index"):
        retrieve([DocumentView(snapshot=fixture.snapshot)], query(text="Alpha"))
    with pytest.raises(ValueError, match="exactly one"):
        retrieve([fixture, fixture], query(text="Alpha"))


def test_direct_context_is_exact_precomputed_and_never_truncated():
    fixture = view()
    result = retrieve([fixture], query(mode="direct"))
    assert result.hits[0].text == fixture.context and result.hits[0].score_kind == "context"
    with pytest.raises(CapabilityUnavailable, match="budget"):
        retrieve([fixture], query(mode="direct", direct_max_chars=1))
    with pytest.raises(CapabilityUnavailable, match="write-time"):
        retrieve([DocumentView(snapshot=fixture.snapshot)], query(mode="direct"))


@pytest.mark.parametrize("predicate", [{"path": "/x~2", "operator": "eq", "value": 1},
                                       {"path": "/x", "operator": "gte", "value": True},
                                       {"path": "/x", "operator": "exists", "value": 1}])
def test_invalid_predicate_is_rejected(predicate):
    with pytest.raises(ValueError):
        FieldPredicate.model_validate(predicate)


def test_null_missing_escape_nested_array_and_typed_equality():
    assert matches({"a/b": [{"~name": None}]}, [FieldPredicate(path="/a~1b/0/~0name", operator="eq", value=None)])
    assert not matches({}, [FieldPredicate(path="/missing", operator="eq", value=None)])
    assert matches({}, [FieldPredicate(path="/missing", operator="exists", value=False)])
    assert not matches({"x": True}, [FieldPredicate(path="/x", operator="eq", value=1)])
    assert matches({"x": 1.0}, [FieldPredicate(path="/x", operator="in", value=[1, 2])])
