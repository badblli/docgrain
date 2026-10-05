# ADR 0009 — Deterministic canonical chunk derivation

Date: 2026-10-01. Status: Accepted for M2c implementation.
Task: https://app.notion.com/p/3e973464cac58116ae26c860b5218cf1
Base: local M2b `4e70e38`; branch `codex/m2c-structure-aware-chunks`.

## Problem / reference review

Existing chunks are demo fixtures or lineage-only contracts, without generated canonical content.
M2c must derive retrieval content without losing table/entity JSON, reading order or evidence.
Primary sources reviewed 2026-10-01:
- [Docling chunking](https://docling-project.github.io/docling/concepts/chunking/): structural
  items and heading/caption metadata form the first boundary; size refinement follows structure.
- [Haystack DocumentSplitter](https://docs.haystack.deepset.ai/docs/documentsplitter): source/page
  metadata survives splitting. Docgrain additionally needs revision-qualified parent dependencies.

We adopt these boundary/context patterns, using Docgrain canonical models rather than a vendor
document or framework dependency. This is a structural correctness spike, not retrieval quality evaluation.

## Decisions

1. Canonical JSON stays unchanged. Derived manifest 0.3.0 adds verified chunk payloads and explicit
   omission records. Historical 0.1/0.2 payload bytes and generated schema files remain unchanged.
2. Traverse container `children` order; never use the physical node-list order. Pack consecutive text
   in one section/list context and role. Tables and entities have dedicated chunks. Context carries
   document/section/list references and evidence; every dependency used in retrieval text has an edge.
3. Store body text, contextualized retrieval text, content checksum, reading order, parent-local ordinal,
   source slices/field pointers and evidence IDs. Text slices use canonical Unicode code points; original
   page/bbox/cell evidence remains authoritative. Text fragments cover original content without trimming.
4. Size budget is explicitly Unicode characters, not model tokens. Oversized text uses whitespace
   boundaries then a character fallback. Atomic table rows and complete entity JSON may overflow the
   soft budget; flag that fact, never truncate a row/JSON object or silently claim a token limit.
5. Tables use JSON row projections retaining cell value/formula/cache/display/span facts and caption.
   Only caller-declared header rows repeat; the current canonical contract lacks reliable header metadata.
   Row intervals and cell evidence are attached per chunk, including repeated header dependencies.
6. Only schema-valid accepted SchemaEntity data becomes an entity chunk. Unaccepted/invalid/legacy
   entities and assets without descriptions are explicitly omitted. Binary images are not interpreted.
   No LLM, confidence, acceptance or semantic normalization is fabricated.
7. Chunk run identity includes canonical revision and the full fixed-version effective strategy config.
   Logical chunk ID includes ordered canonical parents, config/strategy digest, parent-local ordinal and
   retrieval content digest. Unrelated earlier chunks do not shift every subsequent logical ID.
8. Publication regenerates the declared fixed strategy from the stored canonical snapshot and compares
   the whole manifest, rejecting forged content/evidence/context/scope/config. Immutable replay is a no-op;
   multiple strategies/budgets coexist as separate revisions. Reads require an explicit chunk revision.
9. Empty/non-text results return an explicit no-chunks error. Legacy lineage-only manifests remain
   valid history, but are not presented as real generated chunks. Ingestion does not claim this stage done.

## Boundaries / validation plan

Executable contract spike: shuffled node storage, section boundaries, exact Unicode source coverage,
table headers/rows/cell facts, accepted vs pending entities, atomic overflow, deterministic identities.
Integration: isolated PostgreSQL replay/concurrency/tamper/scope, real PDF/DOCX/TXT/XLSX, HTTP
read/write/demo guards, legacy schema parity. Real local documents will be previewed read-only.
Embedding tokenizers, overlap tuning, semantic ranking, incremental invalidation/indexing, product UI
and automatic pipeline wiring remain later work. Existing user data/runtime stay available; no push/merge.

## Validation record — 2026-10-01

- Code audit before starting: M2b `4e70e38` clean; 94 local tests passed, 27 opt-in skipped; Ruff clean.
- Final full worker/PostgreSQL/real Docling suite: **138 passed**. Local **103 passed, 35 opt-in skipped**.
  Ruff, Python compile, TypeScript noEmit, API/worker Docker builds and Compose config passed.
  API image OpenAPI/chunk schema smoke passed. Historical generated schemas unchanged/parity checked.
- Real parser spike PDF/DOCX/TXT/XLSX: source-preserving generation, replay, persisted bidirectional
  lineage and separate canonical/chunk revisions. Test fixture initially omitted the PDF geometry path;
  corrected to use the same verified source path as the worker, then all eight M2c integration cases passed.
- Read-only current user dataset: **222 chunks** — Dobedan PDF 178, Corendon PDF 28, DOCX 3,
  XLSX 9, TXT 4. All 18,825 canonical TextBlock characters and 276 table rows preserved exactly,
  with cell value/formula/cache/display/span facts unchanged. Every chunk evidence ID belongs to source.
- Dobedan has 17 oversized atomic table rows, explicitly flagged rather than truncated. Twenty-three
  binary picture nodes have no semantic description and are recorded as omissions (10 + 13), without
  fabricated text. Binary source assets remain available in the existing Inspector stack.
- Preview artifacts and readable summary live in ignored `data/reviews/`; customer content excluded
  from Git. No re-ingestion, provider/embedding/index call or publication into the user dataset.
- Existing localhost images remain on the separate Inspector/image branch; this stacked M2c branch
  is not deployed there. Commit is local; push/PR/merge require separate authorization.
