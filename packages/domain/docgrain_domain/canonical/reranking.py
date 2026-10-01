"""Conditional reranking of scoped candidates; no hidden provider or fallback."""

import math
from typing import Literal, Protocol

from pydantic import ConfigDict, Field

from .locations import StrictModel


class RerankSpec(StrictModel):
    strategy: Literal["phrase-overlap", "adapter"] = "phrase-overlap"
    version: str = Field(default="1", min_length=1)


class RerankCandidate(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    text: str


class Reranker(Protocol):
    def score(self, query: str, candidates: tuple[RerankCandidate, ...], spec: RerankSpec) -> dict[str, float]: ...


class PhraseReranker:
    def score(self, query, candidates, spec):
        from .retrieval import tokenize

        if spec.strategy != "phrase-overlap" or spec.version != "1":
            raise ValueError("unsupported local reranker configuration")
        terms = set(tokenize(query))
        phrase = " ".join(tokenize(query))
        return {c.key: float(bool(phrase and phrase in " ".join(tokenize(c.text))))
                + len(terms & set(tokenize(c.text))) / max(len(terms), 1) for c in candidates}


def rerank(hits, text, spec, adapter=None):
    if adapter is None and spec.strategy == "adapter":
        from .retrieval import CapabilityUnavailable
        raise CapabilityUnavailable("reranker adapter unavailable")
    candidates = tuple(RerankCandidate(key=h.object_ref.key, text=h.text) for h in hits)
    scores = (adapter or PhraseReranker()).score(text, candidates, spec)
    if set(scores) != {c.key for c in candidates} or any(isinstance(v, bool) or not isinstance(v, (float, int))
                                                       or not math.isfinite(v) for v in scores.values()):
        raise ValueError("reranker must return exactly one finite score per scoped candidate")
    copies = [hit.model_copy(deep=True) for hit in hits]
    for hit in copies:
        hit.component_scores["rerank"] = float(scores[hit.object_ref.key])
    return sorted(copies, key=lambda h: -scores[h.object_ref.key])
