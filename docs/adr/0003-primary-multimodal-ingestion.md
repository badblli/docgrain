# ADR 0003 — Primary page-level multimodal ingestion

- Status: accepted
- Date: 2026-08-31

## Context

Docgrain must understand every structure in a document: prose, headings,
tables, images, charts, diagrams, forms, captions and their layout
relationships. A text-first parser with selective vision fallback does not
provide a uniform guarantee that visual structures on otherwise clean pages are
examined.

The reference ingestion flow renders every page, reads pages with a vision
model in parallel, repairs the document hierarchy, chunks by headings, embeds
the chunks and writes vector and keyword indexes. Page failures must not discard
the rest of a document.

## Decision

Every document page is rendered at 200 DPI and submitted to the configured
primary `VisionProvider`. The hosted default is Gemini Vision; compatible local
or private providers remain replaceable behind the same contract.

- Vision concurrency defaults to four page tasks and is configurable by
  provider profile.
- Each page receives at most three attempts by default.
- Page tasks are idempotently keyed by document version and page number.
- Each page produces Markdown plus structured text/table/asset/chart/form
  regions with bounding boxes, confidence and provider/prompt metadata.
- A document-level join step repairs headings, reading order, captions,
  cross-page tables and references.
- A heading repair output that removes or compresses too much source material
  is rejected; the pre-repair extraction remains available.
- Pages that exhaust retries are recorded in `page_failures`; successful pages
  continue through chunking and indexing and the version publishes as
  `partial`.
- Docling remains a deterministic secondary parser used for cross-checking,
  reconciliation and fallback rather than owning the primary extraction path.

The immutable original and page renders are the ultimate evidence. Accepted
OCR/layout/table extraction may contribute to the canonical normalized
representation. Interpretive descriptions, summaries and inferred
relationships are always marked `derived` and retain evidence-region links.

Model identifiers are configuration, not architecture. Tests target the
`VisionProvider` contract and structured schema rather than a preview model
name.

## Consequences

- Ingestion has predictable per-page model cost, so concurrency, retries,
  caching and usage telemetry are mandatory.
- CI uses a fake provider and golden multimodal fixtures; real Gemini tests are
  explicit integration/evaluation runs with redacted documents and secrets
  supplied through the environment.
- Quality gates validate primary extraction and decide retry, cross-check or
  partial outcomes; they no longer decide whether a page is sent to vision.
- Document-level normalization, graph construction and chunking remain fan-in
  operations so page parallelism cannot destroy cross-page structure.
