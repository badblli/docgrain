"""Offline ranking metrics and reproducible evidence-labeled strategy comparisons."""

import math
from time import perf_counter

from pydantic import Field, JsonValue, model_validator

from .lifecycle import digest
from .locations import StrictModel
from .retrieval import DocumentView, RetrievalQuery, retrieve


def ranking_metrics(retrieved, relevant, *, k):
    if k < 1 or any(not isinstance(g, (float, int)) or isinstance(g, bool) or not math.isfinite(g) or not 0 <= g <= 10 for g in relevant.values()):
        raise ValueError("metric k must be positive and relevance grades finite between 0 and 10")
    ranked = list(dict.fromkeys(retrieved))[:k]
    positive = {key: grade for key, grade in relevant.items() if grade > 0}
    if not positive:
        return {"recall": None, "mrr": None, "ndcg": None, "false_positive": bool(ranked)}
    first = next((rank for rank, key in enumerate(ranked, start=1) if key in positive), None)
    def dcg(grades):
        return sum((2**grade-1)/math.log2(rank+1) for rank, grade in enumerate(grades, start=1))
    ideal = dcg(sorted(positive.values(), reverse=True)[:k])
    return {"recall": len(set(ranked) & positive.keys()) / len(positive), "mrr": 1/first if first else 0,
            "ndcg": dcg([positive.get(key, 0) for key in ranked])/ideal, "false_positive": False}


class GoldenQuery(StrictModel):
    id: str = Field(min_length=1)
    text: str
    relevance: dict[str, float]
    label_kind: str = "evidence"

    @model_validator(mode="after")
    def valid(self):
        if self.label_kind not in {"evidence", "source", "object"}:
            raise ValueError("unsupported golden label kind")
        ranking_metrics([], self.relevance, k=1)
        return self


def hit_labels(result, kind):
    # Preserve hit rank when a hit contains multiple evidence labels; first occurrence wins.
    if kind == "evidence":
        return [f"{hit.document_id}:{evidence.id}" for hit in result.hits for evidence in hit.evidence]
    if kind == "source":
        return [f"{hit.document_id}:{hit.source_revision_id}" for hit in result.hits]
    return [f"{hit.document_id}:{hit.object_ref.object_id}" for hit in result.hits]


def evaluate(views: list[DocumentView], golden: list[GoldenQuery], strategies: dict[str, dict[str, JsonValue]],
             *, workspace_id, document_ids, k=5):
    if len({q.id for q in golden}) != len(golden) or not golden or not strategies:
        raise ValueError("evaluation requires unique nonempty golden queries and strategies")
    fingerprint = digest({"corpus": [v.model_dump(mode="json") for v in views],
                          "golden": [q.model_dump(mode="json") for q in golden], "strategies": strategies,
                          "workspace_id": workspace_id, "document_ids": document_ids, "k": k})
    report = {"version": "1", "fingerprint": fingerprint, "k": k, "strategies": {}, "cost": {"external_calls": 0, "measured_usd": None}}
    for name, options in strategies.items():
        rows = []
        for golden_query in golden:
            request = RetrievalQuery.model_validate({"workspace_id": workspace_id, "document_ids": document_ids,
                                                     "text": golden_query.text, "limit": k, **options})
            started = perf_counter()
            result = retrieve(views, request)
            elapsed = (perf_counter()-started)*1000
            # Relevance labels are evaluated per hit, not per evidence item: a rich hit cannot consume top-k.
            labels_per_hit = []
            for hit in result.hits:
                single = result.model_copy(update={"hits": [hit]})
                labels_per_hit.append(hit_labels(single, golden_query.label_kind))
            metrics = evidence_metrics(labels_per_hit, golden_query.relevance, k=k)
            rows.append({"query_id": golden_query.id, "metrics": metrics, "latency_ms": elapsed,
                         "timings_ms": result.timings_ms, "labels": labels_per_hit,
                         "evidence_bytes": sum(len(e.model_dump_json().encode()) for h in result.hits for e in h.evidence)})
        means = {}
        for metric in ("recall", "mrr", "ndcg"):
            values = [row["metrics"][metric] for row in rows if row["metrics"][metric] is not None]
            means[metric] = sum(values)/len(values) if values else None
        report["strategies"][name] = {"queries": rows, "mean": means,
                                      "no_answer_false_positives": sum(row["metrics"]["false_positive"] for row in rows)}
    return report


def evidence_metrics(labels_per_hit, relevant, *, k):
    """Hit-ranked relevance with evidence union recall; duplicate labels receive no extra gain."""
    ranking_metrics([], relevant, k=k)
    positive = {key: grade for key, grade in relevant.items() if grade > 0}
    if not positive:
        return {"recall": None, "mrr": None, "ndcg": None, "false_positive": bool(labels_per_hit[:k])}
    seen, grades = set(), []
    for labels in labels_per_hit[:k]:
        fresh = set(labels) - seen
        seen.update(labels)
        grades.append(max((positive.get(key, 0) for key in fresh), default=0))
    first = next((i for i, grade in enumerate(grades, 1) if grade), None)
    # Label union defines recall; ideal graded evidence assumes at most one strongest label per hit.
    ideal = sum((2**g-1)/math.log2(i+1) for i, g in enumerate(sorted(positive.values(), reverse=True)[:k], 1))
    actual = sum((2**g-1)/math.log2(i+1) for i, g in enumerate(grades, 1))
    return {"recall": len(seen & positive.keys())/len(positive), "mrr": 1/first if first else 0,
            "ndcg": actual/ideal, "false_positive": False}
