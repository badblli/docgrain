# ADR 0011 — Explicit retrieval modes over pinned canonical knowledge

Date: 2026-10-01. Status: local implementation; review/merge pending.

## Problem / benchmark

M2d safely publishes document index generations. There is no query contract. Exact business
values must remain typed JSON; sending a numeric predicate to vector similarity loses meaning.
Repository benchmark found accepted schema entities with complete field evidence, immutable
generation vectors and atomic heads, but no lexical/ranking implementation or provider adapter.
Primary references reviewed: [BM25 settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity),
[reciprocal rank fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion),
[PostgreSQL JSON operators](https://www.postgresql.org/docs/current/functions-json.html).

## Decision

- Versioned domain query/result contracts: structured, lexical BM25, vector cosine and hybrid
  reciprocal-rank fusion. Choose mode explicitly; no LLM router or numeric-to-vector coercion.
- Require workspace and bounded explicit document IDs. Apply source/schema/typed field filters
  before scoring or corpus statistics. All predicates must match the same accepted, valid entity.
  JSON-pointer predicates never cast strings to numbers or booleans to integers.
- Structured reads use latest canonical revisions and need no vectors. Ranked modes use only
  complete active index generations and the exact snapshots that produced them. Read all
  documents/heads/snapshots in one repeatable-read transaction. No mutable cache key of just doc ID.
- Query vectors are caller-supplied with the complete pinned EmbeddingSpec, validated against
  every searched generation. No server model call, document parsing or embedding on query path.
  Missing generation/unsupported configuration is explicit, never a fake result/fallback.
- Python reference adapter: Unicode casefold word tokenizer without stemming, BM25 k1=1.2,
  b=0.75; exact cosine including zero-norm exclusion; RRF k=60 over bounded child result lists.
  Stable scope-qualified IDs break ties. Backend-independent canonical models remain unchanged.
- Return source revision, processing revision, optional index generation, actual source evidence,
  source/context parents and embedding/index occurrences. Scores state their algorithm and are
  not confidence estimates. Structured hits return authoritative entity JSON.

## Gates / limits

Executable spike: typed numeric filters avoid embeddings; lexical rare-token and multilingual
matching; vector config/dimension/zero checks; pre-ranking tenant/source/schema filters; hybrid
deduplication; missing capability; deletion and concurrent head changes preserve pinned reads.
Use isolated real PostgreSQL. This is a bounded correctness reference, not a production ANN
backend or language morphology model. Semantic quality needs real model/corpus labels in M2f.
