# ADR 0021 — Source reading and immutable manual review

- Date: 2026-10-02
- Status: implemented locally; corpus semantic acceptance remains open.
- Builds on ADR 0017, ADR 0019 and ADR 0020.

## Decision

The default document screen is **Belgeyi incele**. End users read extracted content beside the original source, select a text block, table cell or visual, inspect its source location, and edit a draft. Engineering inspectors remain under **Teknik görünümler**. This is a bounded manual N4 slice that can proceed while N3 automated visual interpretation is still open. It does not close N3 or N5.

PDF pages and normalized bounding boxes are rendered from the pinned source version. Word, Excel and text expose their literal source locators and verified original download. PNG/JPEG use original image regions. No page numbers or visual descriptions are invented. Tables keep typed values and actual grid/merge geometry. First-row header display is an explicitly adjustable presentation hint, not a canonical mutation.

## HTTP contract

| Endpoint | Behavior |
| --- | --- |
| `GET /v1/documents/{document_id}/review?revision_id=...` | Source metadata, canonical snapshot/hash, editable and blocked fields, latest/approved pointers and up to 50 history entries ordered by server record time, independently of self-reported client timestamps. Defaults to latest; historical views are read-only. |
| `POST /v1/documents/{document_id}/reviews/preview` | Pure typed diff; no database or object writes. |
| `POST /v1/documents/{document_id}/reviews` | Explicit source confirmation and matching preview required; immutable child revision plus refreshed AI/Markdown/chunks/publication. |
| `GET /v1/knowledge/revisions/{revision_id}/source` | Original bytes verified against document scope, immutable storage version, size and SHA-256. |

Preview requests carry base revision, snapshot SHA-256, operation ID, aware timestamp, reviewer, reason, and a bounded list of `{field_id,before,after}`. Field IDs are server-generated and revision-scoped. Save adds `preview_id` and actual boolean `confirmed_source: true`. Current head, hash and before values must match. Stale input returns 409; unsupported fields/types/no-op/invalid confirmation return 422. Unavailable or corrupt pinned storage fails before publication.

## Editable scope

- Source-bound TextBlock text, scalar non-formula table values and visual descriptions.
- Source evidence must exist. Source bytes, node IDs, evidence, artifacts, formulas/cached results and geometry are immutable.
- Covered merged cells, compound values and oversized fields are read-only. Native `merge_covered` markers and physical span coverage are honored.
- Integer, floating, boolean and string types are preserved. JSON clients can serialize an integral float as an integer; the source float type is restored before validation.
- Revisions with linked entities, relations or domain records are blocked until dependent fact validation exists.
- Changing fields records human source checking for those fields only; whole-document approval pointer and partial coverage remain unchanged. Reviewer is currently self-reported, not an authenticated identity.

## Atomicity and replay

Source and artifact bytes are verified, and all immutable derived files are staged and verified in MinIO before the SQL transaction. One PostgreSQL transaction appends the child, compare-and-swaps the latest pointer, writes chunk lineage and publishes derived output references. A rollback reveals neither a new head nor a partial publication. Unreferenced staged objects can remain after a failed transaction; retries safely reuse verified bytes. Concurrent different changes produce one winner. Operation ID reuse with a different payload is rejected; exact replay is idempotent, including after the head moves again.

Original canonical/source/artifact payloads and prior output publications remain unchanged. Modern processing identity gets a new spec with review request digest; legacy schema snapshots keep their schema and identity policy. No parser, OCR, provider, embedding or index adapter runs during review save.

## UX and deployment boundaries

Draft edits show original values and a server before/after preview. Edits invalidate preview and source confirmation. The browser keeps drafts across detail tabs, guards navigation and exports drafts as JSON. Conflicts keep the draft and offer export plus explicit loading of the new head. History displays immutable revisions without restore or whole-document approval controls. History is currently capped; pagination, role-based editing and authenticated audit identity are future work before multi-user production deployment. A request aborted after server commit must be resolved through history/idempotent replay; browser cancellation does not roll back a committed transaction.

The next acceptance experiment is Gemini question answering against an explicitly pinned canonical revision with source citations and verified image references. This is a consumer of normalized data, separate from local normalization. It must not write revisions or imply semantic acceptance. Embedding remains after N5.
