# ADR 0008 — External schema entities and field provenance

Date: 2026-09-30. Status: Accepted for M2b implementation.
Task: https://app.notion.com/p/3e973464cac581be9efedc7560d91606
Base: local M2a `a93ac97`; branch `codex/m2b-schema-entities-field-provenance`.

## Problem and primary references

Legacy Entity has free-form properties without a pinned schema or entity acceptance lifecycle.
DomainRecord validates business JSON separately, but does not make entities schema-driven.
Field annotations currently accept arbitrary names rather than checked JSON locations.

Reviewed 2026-09-30:
- [JSON Schema 2020-12 validation](https://json-schema.org/draft/2020-12/json-schema-validation):
  instance constraints are distinct from annotation keywords. `default` never inserts a missing value.
- [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901): field locations use JSON Pointer with `~0`/`~1`
  escaping and explicit array indices, preserving nested/empty/unicode property names.
- [python-jsonschema validation](https://python-jsonschema.readthedocs.io/en/stable/validate/):
  schema checking and instance validation are separate; formats require an explicit FormatChecker.
  We use the supplied Draft 2020-12 document, offline local refs only, and available format checkers.
- Existing Docgrain benchmark: structured data remains authoritative, provenance is field-level,
  schemas are external, retrieval text is a projection and human review is an explicit lifecycle.

## Decisions

1. Add SchemaEntity alongside the historical Entity contract in canonical 0.4.0. It holds logical
   identity, type, schema ID/version, JSON data, complete field provenance, validation and review
   history. Old snapshots/schema files remain unchanged/readable; no hotel/room classes in core.
2. Schema registration is immutable at workspace + logical schema ID + version. The reference
   pins SHA-256 of the exact supplied JSON Schema. Local `$ref`/`$defs` work; external refs and
   unsupported dialects/formats fail explicitly, never cause network access or silent fallback.
3. Every populated JSON leaf (including null and empty containers) has a checked pointer and
   evidence. Evidence and producer IDs must belong to the snapshot. Confidence is optional,
   and a measured confidence requires its method. Confidence never grants acceptance.
4. Entity IDs use document + logical schema ID + explicit natural/extraction key, independent
   of mutable data and schema version. A snapshot uses one version per logical schema ID;
   migrations cannot silently mix or relabel entities from another version.
5. Candidate publication recomputes validation against the registered schema. Invalid candidates
   may be retained for review; acceptance requires valid data. Lifecycle is extracted -> needs_review
   -> accepted/rejected with actor, reason, aware timestamp and decision ID. Decisions append
   canonical revisions with CAS; explicit deterministic inputs make replay a no-op. Terminal
   decisions are immutable; corrected data is a new extraction/review cycle.
6. Processing identity fingerprints the upstream canonical revision and entity/review inputs.
   Original source, nodes, evidence and existing entities stay intact. Entity producer is explicit;
   no fabricated model call, confidence or evidence. CanonicalRepository revalidates schemas and
   entity payloads at publication, including direct callers, before storage/approval.
7. Retrieval JSON text is stored in a separate projection manifest, with content digest and an
   entity occurrence dependency. Derived manifest 0.2.0 adds projection stage/payload; historical
   0.1.0 serialization/schema remains unchanged. Projection cannot write canonical entity data.

## Spike and boundaries

Contract tests demonstrate two unrelated external schemas, nested pointers, invalid data/acceptance
guards, workspace isolation, immutable schema/review history, idempotency/CAS and projection lineage.
A generic canonical table row mapping example produces schema candidates with cell evidence.
This milestone supplies the ingest/review/projection boundary; automatic semantic extraction,
schema discovery, entity UI, LLM calls, chunking and indexing remain later capabilities.

Validation uses isolated PostgreSQL schemas and temporary containers. Existing user documents,
Inspector/image extraction stack and unmerged branches remain available. Push/merge require approval.

## Validation record — 2026-10-01

- Fresh worker image with pinned Docling 2.130.0: **121 tests passed**, including real PDF/DOCX/TXT/XLSX,
  isolated PostgreSQL, schema registry immutability/scope, concurrent review replay/CAS, invalid/forged
  validation rejection, API lifecycle and verified separate projection lineage. Known dependency
  deprecation warnings remain (Starlette test client and Docling OCR/table image options).
- Local environment: **94 passed, 27 opt-in integration tests skipped**. Ruff and Git whitespace
  checks passed; API and worker Docker images built under separate `m2b-validation` tags;
  API image registry/format checker and OpenAPI smoke passed; Compose config validated.
- Read-only actual XLSX `doc_09ab90f4`, table `table_27b101c500a5d260a527efbe4d4b5cad`:
  six schema-valid service candidates from an external `service.schedule.v1` schema and explicit
  A/B/C field mappings. Breakfast fields trace to `f&b!A4`, `f&b!B4`, `f&b!C4`; all 18 fields preserve
  source cell evidence. Source time spelling is retained, without automatic semantic normalization.
  Preview artifacts live under ignored `data/reviews/`; no real customer data is committed.
- Existing running stack remains on the Inspector/image extraction branch, not this stacked branch.
  No re-ingestion, Gemini calls, push, PR or merge; user data remains five documents with completed jobs.
