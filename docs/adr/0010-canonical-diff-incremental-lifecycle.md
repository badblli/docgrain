# ADR 0010: Canonical diff and atomic index generations

Date: 2026-10-01. Status: accepted for local implementation; review/merge pending.

## Problem and benchmark

M2c produces immutable, context-aware chunks. A new source/processing revision changes
occurrences even when retrieval text stays identical. Invalidating every descendant would
unnecessarily embed unchanged table rows; updating a live index in place exposes partial
results and retains deletions after failures. Empty eligible content must also be publishable.

Repository benchmark: canonical/derived rows are immutable, heads use row locks and CAS;
M2c chunk IDs include ordered logical parents, configuration and contextualized content.
Lineage-only historical manifests cannot represent actual vectors. No provider or Qdrant
writer exists. This milestone adds an executable lifecycle boundary, not a provider integration.

Primary references reviewed:
- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html):
  statement snapshots and row locks support a single immutable payload plus transactional head.
- [Qdrant points](https://qdrant.tech/documentation/manage-data/points/): point writes are a
  separate backend operation; they do not share the canonical PostgreSQL transaction.
- [Qdrant collections](https://qdrant.tech/documentation/manage-data/collections/): collection
  lifecycle is a future adapter boundary. No distributed atomicity is claimed here.

## Decision

1. Diff objects by typed collection plus logical ID, with exact JSON-pointer content and
   annotation/evidence changes. Identity shifts remain additions/deletions; no fuzzy matching.
   Walk complete registered lineage to report candidate invalidation. Recompute deterministic
   chunk payloads, then prune candidates by content digest; no incremental parser claim.
2. Embedding inputs are contextualized retrieval text only. Pin provider/model/version,
   dimensions and options. Cache by workspace, document, embedding configuration and digest.
   Refresh chunk sources/evidence/order/occurrence even when reusing vectors. Changing the
   embedding specification invalidates reuse. A full rebuild bypasses cache reads.
3. Use a separate chunk-set contract allowing zero chunks. Historical nonempty manifests and
   their hashes remain unchanged. An empty generation is an explicit removal of all entries.
4. An injected embedder is the execution boundary. No default, fake runtime vector or paid
   model call. PostgreSQL stores actual caller-produced vectors and canonical payloads in an
   immutable generation. Retrieval in M2e must read one active generation ID and its payload.
5. Checkpoint successful embeddings independently. Serialize cooperating builders per document
   with a PostgreSQL advisory lock. Publish a complete generation and CAS the named index head
   in one transaction; canonical latest must still equal the target. Failed/stale builds leave
   the prior head untouched. Old generations remain historical, never active stale entries.
   Successful retries return the stored generation without embedding or rewinding a newer head.
6. Provider calls cannot be exactly-once across a crash between response and checkpoint.
   Stored checkpoints and publications are idempotent. Pinned configurations must produce
   consistent vectors; conflicting cache values fail instead of mutating immutable history.

## Spike and regression gates

Executable tests must show heading/context changes, single cell/row changes, deletions,
evidence-only changes, schema-entity acceptance/removal, config changes, empty results,
checkpointed retry, finite/dimension-valid vectors, partial provider and SQL failures,
concurrent duplicate/stale builders, immutable scope verification, and full rebuild equivalence.
Use real PostgreSQL and real TXT/XLSX parsing in isolated schemas. User snapshots may be
used for read-only counterfactual previews; label them explicitly. Preserve current runtime.

## Limits

Generation payload storage rewrites the complete entry set; embeddings alone are selective.
No Qdrant materialization, automatic ingestion wiring, scheduling, collection-wide search,
distributed backend swap, garbage collection or product UI is delivered by this milestone.
The programmatic worker service is the writer; HTTP exposes read-only diff/plan/active state.

## Local validation outcome

Fresh worker image with real PostgreSQL/Docling: 161 tests passed (23 M2d tests included).
Local minimal environment: 115 passed, 46 opt-in tests skipped. Ruff, compileall, TypeScript,
API/worker Docker builds, API image import/OpenAPI/schema smoke, compose config and Git
whitespace checks passed. Existing upstream Starlette/Docling deprecation warnings remain.
Real TXT/XLSX edits produced verified new source revisions in isolated schemas. Read-only
counterfactual XLSX/PDF previews demonstrated one-cell replacement, row removal and evidence-only
refresh; no user source/revision was persisted or re-ingested. Test-only vectors are explicitly
injected. Live localhost API/web and all five completed user jobs were rechecked unchanged.
Review/merge remains pending; no push, PR or runtime deployment.
