# ADR 0007 — Stable identity, revisions and lineage

Date: 2026-09-30. Status: Accepted for M2a implementation.
Task: https://app.notion.com/p/3e973464cac5813ca13ec9c2ba22b3f4

## Problem

M1 source IDs include upload/object versions and processing IDs omit effective configuration.
PDF identity includes mutable text and ancestor keys. Retries can rewrite asset versions and
conflict with an otherwise identical revision. There is no revision-qualified downstream lineage.

## Primary-source benchmark

Reviewed 2026-09-30:

- [Pathway core concepts](https://pathway.com/developers/user-guide/introduction/concepts/):
  stable primary keys identify rows; updates retract old rows and insert replacements;
  affected changes propagate through dataflow. Adopt explicit dependency edges and separate
  logical identity from immutable occurrences. Actual invalidation/recomputation is M2d.
- [R2R identity utilities](https://github.com/SciPhi-AI/R2R/blob/main/py/shared/utils/base_utils.py):
  deterministic document IDs use filename/user; extraction IDs include document/ordinal/version.
  Adopt scoped deterministic keys; do not use filenames as logical identity (rename/collision).
- [R2R ingestion service](https://github.com/SciPhi-AI/R2R/blob/main/py/core/main/services/ingestion_service.py):
  explicit ingestion status/version, version-qualified extraction IDs and duplicate conflict guards.
  Adopt explicit immutable lifecycle boundaries and idempotent publication, preserving Docgrain's
  richer canonical contract. Neither project becomes a runtime dependency.

## Decisions and executable spikes

1. Existing document ID is the caller's logical source identity. A deterministic connector-key
   helper is supplied for future adapters. Independent uploads remain separate documents;
   filename/content equality never merges documents or tenants automatically.
2. SourceVersion is the SourceRevision: ID hashes workspace + document + verified SHA-256.
   Bytes, not parser configuration or storage receipt, determine source revision. First verified
   storage receipt is retained immutably on subsequent uploads of identical bytes in that document.
3. ProcessingSpec fingerprints parser/version, dependency versions, effective options,
   mapping strategy, identity policy and schema. KnowledgeRevision is the ProcessingRevision:
   ID hashes source revision + spec digest. Parent is chronology, not identity. Replaying an older
   revision validates its original payload and leaves latest/approved pointers untouched.
   Processing `created_at` uses the retained source receipt time to make concurrent replay
   deterministic; database row `created_at` records publication time, parents record chronology.
4. Identity policy 0.2.0 uses source anchors without text or ancestor context: PDF page/normalized
   bbox, DOCX part/OOXML path, TXT start offset, XLSX sheet/range. Same-kind collisions use ordered
   occurrence. IDs preserve unchanged anchors across processing strategies; parser split/merge,
   shifted offsets/ranges/layout are conservative new identities, not fuzzy matches. Natural
   entity keys must be explicit schema-scoped keys; schema extraction is M2b.
5. DerivedRevision is separate from source/processing: chunking, embedding, indexing each have
   their own config digest and exact upstream revisions. Backend/model changes don't alter sources.
   Chunk identity binds ordered canonical parent IDs, strategy, ordinal and content fingerprint;
   generation is M2c, not provided by M2a.
6. Lineage uses typed, revision-qualified object references. Immutable derived manifests extend
   the source -> processing -> canonical -> chunk -> embedding -> index DAG. Lexical indexes may
   depend directly on chunks. Publication validates known upstream objects, stage order and scope
   under the document head lock; duplicate manifests are no-ops, conflicting payloads fail.
   Queries traverse forward/backward without mixing occurrences of the same logical object.
7. Canonical 0.3.0 adds the processing spec and identity policy 0.2.0. Historical schemas 0.1.0/
   0.2.0 remain byte-for-byte unchanged and old snapshots remain readable. Old sources/revisions
   are never rewritten. Reprocessing a legacy revision starts a new 0.3.0 lineage.

Tests in `test_m2a_lifecycle.py` and PostgreSQL/real-parser integration tests are the executable
spikes: deterministic replay, config-only change, unchanged source anchors, scoped derived
revisions, bidirectional trace, duplicate publication and concurrent CAS. A full parse replay
must match immutable payload, not merely an ID; conflicting nondeterministic output fails closed.

## Boundaries and migration

No entity extractor, chunk generator, embedding call, search engine, fuzzy cross-source matching,
automatic stale-entry deletion, connector watcher or crash recovery is added. Derived manifests
are a storage/query contract for those milestones, not claims that embeddings exist. Canonical
writer supports reparse publication with CAS and replay; user-facing reprocess job API remains
separate future lifecycle work. The running Inspector/image-fix stack is on an unmerged feature
branch; M2a validation uses isolated test schemas/containers and does not downgrade that stack.

## Validation record — 2026-09-30

- Local suite: 88 passed, 20 environment-gated tests skipped.
- Worker-image suite with PostgreSQL in disposable schemas and real Docling: 108 passed.
- Final effective-option capture adjustment: 7 PostgreSQL lifecycle tests passed, including
  two actual parses each of PDF/DOCX/TXT/XLSX, processing change and forward/backward lineage.
- Ruff, Python compile, diff whitespace check and Compose configuration passed.
- API and worker validation images built under separate tags; OpenAPI and worker import smoke passed.
- Historical canonical 0.1.0/0.2.0 schema files unchanged; legacy serialized revisions omit the new
  optional processing field to preserve historical payload hashes. No user source, job, snapshot,
  running service, Gemini call or remote Git operation was changed by this validation.
