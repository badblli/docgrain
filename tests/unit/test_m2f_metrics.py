"""Hand-calculated metric spike; no dependence on a scorer's implementation."""

import math

import pytest
from docgrain_domain.canonical.evaluation import GoldenQuery, evaluate, ranking_metrics
from docgrain_domain.canonical.reranking import RerankSpec
from docgrain_domain.canonical.retrieval import (
    CapabilityUnavailable,
    RetrievalQuery,
    retrieve,
)

from tests.fixtures.retrieval import view


def test_metrics_use_unique_results_and_graded_discount():
    result = ranking_metrics(["irrelevant", "a", "a", "b"], {"a": 3, "b": 1}, k=3)
    assert result["recall"] == 1
    assert result["mrr"] == 0.5
    assert math.isclose(result["ndcg"], (7/math.log2(3) + 1/math.log2(4)) / (7 + 1/math.log2(3)))


def test_empty_labels_and_no_answer_metrics_are_explicit():
    assert ranking_metrics([], {"a": 1}, k=5)["mrr"] == 0
    assert ranking_metrics(["x"], {}, k=5) == {"recall": None, "mrr": None, "ndcg": None, "false_positive": True}
    with pytest.raises(ValueError):
        ranking_metrics(["a"], {"a": -1}, k=2)


def test_conditional_rerank_expands_candidates_preserves_payload_and_rejects_injection():
    fixture = view()
    base = RetrievalQuery(workspace_id="workspace-test", document_ids=["document-test"], mode="lexical", text="Alpha", limit=1)
    class Reverse:
        def score(self, _query, candidates, _spec):
            assert len(candidates) == 3
            return {c.key: float(i) for i, c in enumerate(candidates)}
    plain = retrieve([fixture], base)
    request = base.model_copy(update={"reranking": RerankSpec(strategy="adapter")})
    reranked = retrieve([fixture], request, reranker=Reverse())
    assert reranked.hits[0].object_ref != plain.hits[0].object_ref and reranked.reranker_used == "adapter:1"
    expected = next(e for e in fixture.generation.entries if e.chunk.object_ref == reranked.hits[0].object_ref)
    assert reranked.hits[0].text == expected.chunk.retrieval_text and reranked.hits[0].evidence
    class Inject:
        def score(self, *_):
            return {"other-workspace": 1.0}
    with pytest.raises(ValueError, match="scoped"):
        retrieve([fixture], request, reranker=Inject())
    with pytest.raises(CapabilityUnavailable, match="adapter"):
        retrieve([fixture], request)
    direct = base.model_copy(update={"mode": "direct", "reranking": request.reranking})
    assert retrieve([fixture], direct, reranker=Inject()).reranker_used is None


def test_dataset_fingerprint_determinism_and_strategy_comparison():
    fixture = view(vector_for=lambda c: [0.0, 1.0] if "Beta" in c.retrieval_text else [1.0, 0.0])
    target = fixture.generation.entries[-1].chunk.object_ref.object_id
    golden = [GoldenQuery(id="beta", text="Beta", label_kind="object", relevance={"document-test:" + target: 2}),
              GoldenQuery(id="none", text="does_not_exist", label_kind="object", relevance={})]
    vector = {"spec": fixture.generation.spec.embedding.model_dump(mode="json"), "vector": [0.0, 1.0]}
    strategies = {"lexical": {"mode": "lexical"}, "vector": {"mode": "vector", "query_embedding": vector},
                  "hybrid": {"mode": "hybrid", "query_embedding": vector},
                  "lexical-rerank": {"mode": "lexical", "reranking": {}}}
    report = evaluate([fixture], golden, strategies, workspace_id="workspace-test", document_ids=["document-test"], k=1)
    assert report["strategies"]["lexical"]["mean"] == {"recall": 1.0, "mrr": 1.0, "ndcg": 1.0}
    assert report["strategies"]["lexical"]["no_answer_false_positives"] == 0
    assert report["strategies"]["vector"]["no_answer_false_positives"] == 1
    assert report["fingerprint"] == evaluate([fixture], golden, strategies, workspace_id="workspace-test", document_ids=["document-test"], k=1)["fingerprint"]
    assert report["cost"]["measured_usd"] is None
