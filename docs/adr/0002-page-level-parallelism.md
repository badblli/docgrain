# ADR 0002 — Page-level parallelism, and where it stops

- Status: accepted
- Date: 2026-08-31

## Context

A 500-page PDF rendered and vision-read serially takes tens of minutes. The
obvious remedy is to split the document by page and fan the work out across
workers. The question is which stages may be split, because Docgrain exists to
preserve exactly the structure that naive splitting destroys.

## Decision

**The unit of parallelism is the page, for `render` and `vision` only.**

| Stage | Unit | Why |
|---|---|---|
| `register` | document | one hash, one version row |
| `render` | **page** | embarrassingly parallel; a page render depends on nothing else |
| `extract` | document | Docling needs the whole file to build reading order and the section tree |
| `quality` | page | pure per-page heuristics over extract output |
| `vision` | **page** | one page image per request; bounded context is what makes a VLM accurate |
| `normalize` | document | operates on the canonical Markdown |
| `chunk` | document | headings, sections and tables span pages |
| `enrich` | document | inherits the heading path built above |
| `embed` | batch | provider-side batching, not page fan-out |
| `publish` | document | one manifest, written once |

**Parallelism buys three things, and speed is only the first.**

1. *Latency* — 48 renders across 8 workers finish in an eighth of the time.
2. *Isolation* — one page that fails does not kill the job. The failure lands
   in `page_failures`, the version publishes as `partial`, and the rest is
   searchable. This is the reason the `partial` state exists at all.
3. *Retryability and cost control* — a single page can be replayed without
   re-running the document, and hosted vision concurrency can be capped to
   respect rate limits and budget.

**Fan-out rules.**

- Each page task is keyed by `(document_version_id, page_number)` and is
  idempotent: re-running it overwrites the same artifact URI.
- A fan-out stage completes only when every page task has reported terminal
  status. The join step writes the stage's aggregate result.
- Vision concurrency is configured per provider profile (hosted Gemini and a
  local Qwen2.5-VL profile have very different limits), not per job.
- Page tasks never write to the document-level artifacts; only the join step
  does. This keeps the concurrent writers disjoint.

**Where splitting is explicitly forbidden.** Chunking must never run per page.
A section that starts on page 12 and ends on page 15 has to become one chunk
tree, and a table spanning a page break has to stay one table. Page-wise
chunking reproduces exactly the flattened-RAG failure Docgrain is a reaction
to.

**Escape hatch for very large documents.** Above a configurable page count,
`extract` may shard into overlapping page ranges parsed in parallel and then
stitched, with the overlap used to reconcile the section tree at the seams.
This is an optimisation with a real correctness cost; it is off by default and
its output is flagged in the manifest.

## Consequences

- The worker needs a fan-out/join primitive, not just a linear stage runner.
- Stage progress becomes "38 / 48 pages", so `StageRun.attributes` carries
  page counters and the console renders a per-stage progress figure.
- `partial` becomes the common outcome for messy scanned documents rather than
  an exceptional one, so the page-level failure report is a first-class screen.
