# M2e — Consumer retrieval contract

`POST /v1/knowledge/retrieve` accepts explicit `workspace_id`, 1–100 unique `document_ids`
and `mode`: structured, direct, lexical, vector or hybrid. Results include strategy, score kind,
pinned canonical/index revisions, exact source evidence/locators and typed upstream lineage.

```json
{"workspace_id":"workspace-test","document_ids":["document-test"],"mode":"structured",
 "schemas":[{"id":"hotel.room.v1","version":"1"}],
 "predicates":[{"path":"/capacity","operator":"gte","value":4}],"limit":10}
```

The schema is caller-owned, not a hotel-specific core dependency. Structured lookup filters
accepted schema-valid entity JSON without vectors. RFC6901 predicates support eq/ne, numeric
gt/gte/lt/lte, in and exists. Missing differs from null; strings/booleans are not numeric casts.
All schema/entity/data predicates apply to the same entity before scoring/corpus statistics.
Optional source revision filters apply before ranking. Workspace/document access is enforced
by storage scope; authentication/authorization deployment is a separate product concern.

Lexical uses Unicode casefold word tokens, BM25 k1=1.2/b=0.75. Vector uses exact cosine;
zero vectors are excluded and finite query vectors require the exact active EmbeddingSpec.
Hybrid uses reciprocal rank fusion k=60 and bounded child candidate lists. Stable IDs break
ties. Scores are ranking signals, not confidence. The Python reference is not an ANN backend,
language stemming model or production semantic quality claim.

Ranked modes require stored active generations; snapshots come from those exact generations,
even if a newer canonical revision is still being indexed. Multi-document reads use one
repeatable-read transaction. Deleted knowledge disappears after the atomic generation switch.
Caller-supplied query embeddings keep ordinary document embedding and provider calls out of
the online HTTP path. Unsupported generation/config is 409, missing/scoped-out document is
404, bad request is 422. Demo produces no fake canonical search result.

Direct mode returns a complete, precomputed JSON context projection. It is written in the
canonical append transaction, with structure, accepted entities, relations, records and artifact
metadata. The explicit `direct_max_chars` budget rejects oversized results; it never silently
truncates. Old revisions can be backfilled using `RetrievalRepository.backfill_context` as an
explicit migration outside queries. Direct mode rejects entity filters: use structured instead.

`timings_ms` distinguishes backend read, query, service and zero embed/rerank work. Transport
and serialization are measured independently by the benchmark harness. Direct/structured use
latest canonical revisions; ranked modes use active index revisions. No automatic router or
silent path fallback is implemented. [ADR 0011](adr/0011-retrieval-capabilities.md).
