# ADR 0001 — Review console architecture and the `/v1` contract

- Status: accepted
- Date: 2026-08-31
- Supersedes: nothing

## Context

Docgrain is a standalone ingestion service used by Luwi and by other
consumers. Its web application is an operations and quality-review console,
not an end-user chatbot. The console must be buildable before PostgreSQL, the
worker and object storage exist, and it must never become the reason a
contract changes.

## Decision

**The API contract is designed before the UI, and the UI is built against it.**
Screens are drawn from endpoint responses, not the other way round. Every
screen in the console maps to exactly one primary endpoint:

| Screen | Primary endpoint |
|---|---|
| Documents list + upload | `GET /v1/documents`, `POST /v1/documents` |
| Pipeline | `GET /v1/jobs/{job_id}` |
| Pages (side-by-side viewer) | `GET /v1/versions/{id}/pages`, `.../pages/{n}` |
| Chunk explorer | `GET /v1/versions/{id}/chunks`, `GET /v1/chunks/{id}/neighbors` |
| Boundary audit | `GET /v1/versions/{id}/chunks/boundaries` |
| Tables and assets | `GET /v1/versions/{id}/tables`, `.../assets` |
| Versions | `GET /v1/versions/{id}/diff?base=` |
| Providers | `GET /v1/providers/health` |

**The web app talks only to the HTTP API.** It never reaches into object
storage, PostgreSQL or Qdrant. Page renders and originals are served through
short-lived signed URLs the API mints; the browser never holds storage
credentials.

**Frontend stack.** Next.js App Router with TypeScript. Server Components do
the reads (list pages, document detail, page artifacts); Client Components own
the interactive surfaces (page selector, chunk explorer, similarity panels).
TanStack Query handles the client-side polling of running jobs. Types are
generated from the API's OpenAPI schema rather than hand-written, so a
contract change breaks the build instead of the console.

**Job progress is polled, not pushed, in the first milestone.** `GET /v1/jobs/{id}`
every 2s while a job is non-terminal. Server-Sent Events are a later
optimisation and must not change the response shape.

**Provenance is resolved server-side.** `GET /v1/versions/{id}/pages/{n}`
returns the page's `table_ids`, `asset_ids` and `chunk_ids` already joined, so
the console never has to stitch four endpoints to draw one screen.

**Derived content is visually distinct, always.** Anything a vision model
produced carries `derived: true` (or `caption_is_derived`) and renders in the
console's violet treatment. Canonical Docling output is never displayed as
though a model wrote it, and never overwritten by one.

**Fixtures ship with the API, not the UI.** While persistence is unimplemented
`docgrain_api.fixtures` serves the real response shapes. Replacing it with a
repository backed by PostgreSQL must not require touching a router signature
or a component.

## Consequences

- The console can be demoed and reviewed today; the backend catches up behind
  a stable contract.
- Any new screen starts with an endpoint proposal, which keeps UI convenience
  from leaking into the data model.
- Contract changes require a new ADR or a migration note.
