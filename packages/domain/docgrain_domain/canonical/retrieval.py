"""Backend-independent retrieval contracts and a deterministic reference scorer."""

from __future__ import annotations

import math
import re
from collections import Counter
from time import perf_counter
from typing import Literal

from pydantic import Field, JsonValue, StrictFloat, model_validator

from .entity_fields import resolve_pointer
from .identity import canonical_json_bytes
from .indexing import EmbeddingSpec, IndexGeneration
from .lineage import ObjectRef
from .locations import StrictModel
from .models import CanonicalKnowledgeSnapshot, Evidence, SchemaEntity
from .reranking import RerankSpec, rerank


class CapabilityUnavailable(ValueError):
    pass


class FieldPredicate(StrictModel):
    path: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "exists"]
    value: JsonValue = None

    @model_validator(mode="after")
    def valid(self):
        # Validate escapes even when the target field is missing.
        if self.path and not self.path.startswith("/") or re.search(r"~(?![01])", self.path):
            raise ValueError("predicate path must be an RFC6901 pointer")
        if self.operator in {"gt", "gte", "lt", "lte"} and not _number(self.value):
            raise ValueError("range predicate requires a finite number")
        if self.operator == "exists" and not isinstance(self.value, bool):
            raise ValueError("exists predicate requires a boolean")
        if self.operator == "in" and (not isinstance(self.value, list) or len(self.value) > 100):
            raise ValueError("in predicate requires at most 100 values")
        return self


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _equal(left, right):
    return left == right if _number(left) and _number(right) else canonical_json_bytes(left) == canonical_json_bytes(right)


def matches(data, predicates):
    for predicate in predicates:
        try:
            actual = resolve_pointer(data, predicate.path)
            exists = True
        except ValueError:
            actual, exists = None, False
        op, expected = predicate.operator, predicate.value
        if op == "exists":
            passed = exists == expected
        elif not exists:
            passed = False
        elif op in {"eq", "ne"}:
            passed = _equal(actual, expected) == (op == "eq")
        elif op == "in":
            passed = any(_equal(actual, value) for value in expected)
        elif not _number(actual):
            passed = False
        else:
            passed = {"gt": actual > expected, "gte": actual >= expected,
                      "lt": actual < expected, "lte": actual <= expected}[op]
        if not passed:
            return False
    return True


class SchemaFilter(StrictModel):
    id: str = Field(min_length=1)
    version: str | None = None


class QueryEmbedding(StrictModel):
    spec: EmbeddingSpec
    vector: list[StrictFloat]

    @model_validator(mode="after")
    def verified(self):
        self.spec.validate_vector(self.vector)
        if not any(self.vector):
            raise ValueError("query vector must have nonzero norm")
        return self


class RetrievalQuery(StrictModel):
    workspace_id: str = Field(min_length=1)
    document_ids: list[str] = Field(min_length=1, max_length=100)
    mode: Literal["structured", "direct", "lexical", "vector", "hybrid"]
    text: str = Field(default="", max_length=10000)
    query_embedding: QueryEmbedding | None = None
    source_revision_ids: list[str] = Field(default_factory=list, max_length=100)
    schemas: list[SchemaFilter] = Field(default_factory=list, max_length=20)
    predicates: list[FieldPredicate] = Field(default_factory=list, max_length=30)
    entity_ids: list[str] = Field(default_factory=list, max_length=100)
    index_name: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,100}$")
    limit: int = Field(default=10, ge=1, le=100)
    candidate_limit: int = Field(default=100, ge=1, le=1000)
    direct_max_chars: int = Field(default=32000, ge=1, le=1000000)
    reranking: RerankSpec | None = None

    @model_validator(mode="after")
    def usable(self):
        if len(set(self.document_ids)) != len(self.document_ids) or any(not key for key in self.document_ids):
            raise ValueError("document IDs must be unique and nonempty")
        if self.mode in {"lexical", "hybrid"} and not tokenize(self.text):
            raise ValueError("lexical/hybrid requires nonempty query terms")
        if (self.mode in {"vector", "hybrid"}) != (self.query_embedding is not None):
            raise ValueError("query embedding is required only for vector/hybrid")
        if self.candidate_limit < self.limit:
            raise ValueError("candidate limit must cover final result limit")
        if self.mode == "direct" and (self.schemas or self.predicates or self.entity_ids):
            raise ValueError("filtered entity lookup requires structured mode")
        return self


class RetrievalHit(StrictModel):
    object_ref: ObjectRef
    document_id: str
    source_revision_id: str
    processing_revision_id: str
    generation_id: str | None = None
    schema_id: str | None = None
    schema_version: str | None = None
    text: str
    data: JsonValue = None
    score: float
    score_kind: Literal["exact", "context", "bm25", "cosine", "rrf"]
    component_scores: dict[str, float] = Field(default_factory=dict)
    evidence: list[Evidence]
    lineage: list[ObjectRef]


class RetrievalResult(StrictModel):
    contract_version: Literal["0.1.0"] = "0.1.0"
    strategy_used: str
    backend: str = "canonical-python-reference-1"
    pinned_revisions: dict[str, str]
    pinned_generations: dict[str, str]
    hits: list[RetrievalHit]
    timings_ms: dict[str, float] = Field(default_factory=dict)
    reranker_used: str | None = None


class DocumentView(StrictModel):
    snapshot: CanonicalKnowledgeSnapshot
    generation: IndexGeneration | None = None
    context: str | None = None

    @model_validator(mode="after")
    def pinned(self):
        if self.generation and (self.snapshot.workspace_id, self.snapshot.document_id, self.snapshot.knowledge_revision.id) != (
            self.generation.revision.workspace_id, self.generation.revision.document_id, self.generation.revision.processing_revision_id
        ):
            raise ValueError("retrieval view canonical/index scope mismatch")
        return self


def context_projection(snapshot):
    """Write-time projection. Keep structure and accepted data exact; never summarize with a model."""
    payload = {"document_id": snapshot.document_id, "root_node_id": snapshot.root_node_id,
               "structure": [node.model_dump(mode="json") for node in snapshot.structure],
               "entities": [entity.model_dump(mode="json") for entity in snapshot.entities
                            if isinstance(entity, SchemaEntity) and entity.review_status == "accepted"
                            and entity.validation.status == "valid"],
               "relations": [r.model_dump(mode="json") for r in snapshot.relations],
               "records": [r.model_dump(mode="json") for r in snapshot.records],
               "artifacts": [r.model_dump(mode="json") for r in snapshot.artifacts]}
    return canonical_json_bytes(payload).decode()


def tokenize(text):
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def bm25(texts, query):
    documents = [Counter(tokenize(text)) for text in texts]
    lengths = [sum(doc.values()) for doc in documents]
    average = sum(lengths) / len(lengths) if lengths else 0
    terms = sorted(set(tokenize(query)))
    frequencies = {term: sum(term in doc for doc in documents) for term in terms}
    scores = []
    for doc, length in zip(documents, lengths, strict=True):
        score = 0.0
        for term in terms:
            count = doc[term]
            if count and average:
                idf = math.log1p((len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
                score += idf * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / average))
        scores.append(score)
    return scores


def cosine(left, right):
    # Scale first: even hypot over many finite numbers can overflow its final norm.
    a, b = max(map(abs, left), default=0), max(map(abs, right), default=0)
    if not a or not b:
        return None
    x, y = [v/a for v in left], [v/b for v in right]
    na, nb = math.hypot(*x), math.hypot(*y)
    return max(-1.0, min(1.0, math.fsum((u / na) * (v / nb) for u, v in zip(x, y, strict=True))))


def retrieve(views: list[DocumentView], request: RetrievalQuery, *, reranker=None) -> RetrievalResult:
    request = RetrievalQuery.model_validate(request.model_dump(mode="json"))
    scoped = [v for v in views if v.snapshot.workspace_id == request.workspace_id
              and v.snapshot.document_id in request.document_ids
              and (not request.source_revision_ids or v.snapshot.source_version.id in request.source_revision_ids)]
    if len({v.snapshot.document_id for v in scoped}) != len(scoped):
        raise ValueError("retrieval view must pin exactly one revision per document")
    result = RetrievalResult(strategy_used=request.mode, hits=[],
                             pinned_revisions={v.snapshot.document_id: v.snapshot.knowledge_revision.id for v in scoped},
                             pinned_generations={v.snapshot.document_id: v.generation.revision.id for v in scoped if v.generation})
    candidates = []
    for view in scoped:
        snapshot = view.snapshot
        eligible = {e.id: e for e in snapshot.entities if isinstance(e, SchemaEntity)
                    and e.review_status == "accepted" and e.validation.status == "valid"
                    and (not request.entity_ids or e.id in request.entity_ids)
                    and (not request.schemas or any(e.schema_id == s.id and (s.version is None or e.schema_version == s.version) for s in request.schemas))
                    and matches(e.data, request.predicates)}
        if request.mode == "structured":
            for entity in eligible.values():
                ref = ObjectRef(kind="canonical", revision_id=snapshot.knowledge_revision.id, object_id=entity.id)
                evidence = sorted({r for a in [entity.annotation, *entity.field_annotations.values()] for r in a.provenance.evidence_ids})
                candidates.append(_hit(snapshot, ref, canonical_json_bytes(entity.data).decode(), evidence, [ref],
                                       schema=entity, data=entity.data))
        elif request.mode == "direct":
            if view.context is None:
                raise CapabilityUnavailable("write-time direct context projection unavailable")
            candidates.append(_hit(snapshot, ObjectRef(kind="canonical", revision_id=snapshot.knowledge_revision.id,
                                                       object_id=snapshot.root_node_id), view.context,
                                   [e.id for e in snapshot.evidence],
                                   [ObjectRef(kind="canonical", revision_id=snapshot.knowledge_revision.id, object_id=n.id) for n in snapshot.structure]))
        else:
            if view.generation is None:
                raise CapabilityUnavailable("active index generation unavailable")
            if request.query_embedding and request.query_embedding.spec != view.generation.spec.embedding:
                raise CapabilityUnavailable("query embedding configuration differs from active index")
            for entry in view.generation.entries:
                entity = next((eligible[s.object_ref.object_id] for s in entry.chunk.sources if s.object_ref.object_id in eligible), None)
                if (request.schemas or request.predicates or request.entity_ids) and entity is None:
                    continue
                hit = _hit(snapshot, entry.chunk.object_ref, entry.chunk.retrieval_text, entry.chunk.evidence_ids,
                           [*entry.chunk.parents, entry.chunk.object_ref, entry.embedding_ref, entry.index_ref],
                           generation_id=view.generation.revision.id, schema=entity)
                candidates.append((hit, entry.vector))
    def key(hit):
        return (hit.document_id, hit.object_ref.object_id)
    if request.mode in {"structured", "direct"}:
        candidates.sort(key=key)
        if request.mode == "direct" and sum(len(h.text) for h in candidates) > request.direct_max_chars:
            raise CapabilityUnavailable("direct context exceeds explicit character budget; use another mode")
        if request.mode == "direct" and len(candidates) > request.limit:
            raise CapabilityUnavailable("direct context limit would omit documents")
        for hit in candidates:
            hit.score, hit.score_kind = 1.0, "exact" if request.mode == "structured" else "context"
        result.hits = candidates[:request.limit]
        return result
    lexical = bm25([hit.text for hit, _ in candidates], request.text) if request.mode in {"lexical", "hybrid"} else []
    dense = [cosine(request.query_embedding.vector, vector) for _, vector in candidates] if request.query_embedding else []
    ranks = {}
    for algorithm, scores in (("bm25", lexical), ("cosine", dense)):
        ordered = sorted((i for i, score in enumerate(scores) if score is not None and (algorithm != "bm25" or score > 0)),
                         key=lambda i: (-scores[i], key(candidates[i][0])))[:request.candidate_limit]
        for rank, index in enumerate(ordered, start=1):
            ranks.setdefault(index, {})[algorithm] = rank
            candidates[index][0].component_scores[algorithm] = scores[index]
    hits = []
    for index, components in ranks.items():
        hit = candidates[index][0]
        hit.score_kind = "rrf" if request.mode == "hybrid" else ("bm25" if lexical else "cosine")
        hit.score = sum(1 / (60 + rank) for rank in components.values()) if request.mode == "hybrid" else next(iter(hit.component_scores.values()))
        hits.append(hit)
    ordered = sorted(hits, key=lambda hit: (-hit.score, key(hit)))
    if request.reranking:
        started = perf_counter()
        ordered = rerank(ordered[:request.candidate_limit], request.text, request.reranking, reranker)
        result.timings_ms["rerank"] = (perf_counter()-started)*1000
        result.reranker_used = request.reranking.strategy + ":" + request.reranking.version
    result.hits = ordered[:request.limit]
    return result


def _hit(snapshot, ref, text, evidence_ids, refs, *, generation_id=None, schema=None, data=None):
    evidence = {e.id: e for e in snapshot.evidence}
    if any(key not in evidence for key in evidence_ids):
        raise ValueError("retrieval evidence must resolve to pinned canonical snapshot")
    lineage = [ObjectRef(kind="source", revision_id=snapshot.source_version.id, object_id=snapshot.document_id),
               ObjectRef(kind="processing", revision_id=snapshot.knowledge_revision.id, object_id=snapshot.document_id), *refs]
    return RetrievalHit(object_ref=ref, document_id=snapshot.document_id, source_revision_id=snapshot.source_version.id,
                        processing_revision_id=snapshot.knowledge_revision.id, generation_id=generation_id,
                        schema_id=schema.schema_id if schema else None, schema_version=schema.schema_version if schema else None,
                        text=text, data=data, score=0, score_kind="exact", evidence=[evidence[key] for key in dict.fromkeys(evidence_ids)],
                        lineage=list({item.key: item for item in lineage}.values()))
