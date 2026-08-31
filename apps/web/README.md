# Web application

The Next.js application is a document-operations console, not an end-user
chatbot. It consumes the documented HTTP API only; it must not access object
storage or databases directly.

A clickable prototype of every screen below exists and is the reference for
layout, terminology and states. See [ADR 0001](../../docs/adr/0001-review-console-and-api-contract.md).

## Route map

```text
/                                   documents list + upload
/documents/[documentId]             redirects to the latest version
/documents/[documentId]/[versionId]
    /pipeline                       ten-stage job view, per-stage detail, retry
    /pages/[pageNumber]             original render | extracted markdown/JSON side by side
    /chunks/[chunkId]               chunk explorer, provenance, cosine neighbours
    /artifacts                      tables and assets gallery
    /versions                       version comparison
/jobs                               global job queue
/providers                          provider health and usage
```

## Composition rules

1. Reads happen in Server Components. Interactive surfaces (page selector,
   chunk explorer, similarity panels, retry buttons) are Client Components
   that receive already-fetched data as props.
2. Running jobs are polled client-side with TanStack Query at 2s while the job
   is non-terminal, then the query stops. No websockets in Milestone 0.
3. API types are generated from OpenAPI into `lib/api/schema.d.ts`. Nothing
   hand-types a response shape.
4. Originals and page renders load from short-lived signed URLs the API mints.
   No storage credentials reach the browser.
5. Derived content — anything a vision model produced — is rendered in the
   violet treatment and labelled. It is never presented as canonical
   extraction.
6. Every artifact view links back to its source: chunk to page, page to the
   original file, table and asset to the page they were lifted from. A screen
   that cannot answer "where did this come from" is not finished.

## Screen states

Each screen must handle: loading, empty, partial (some pages failed), failed,
and stale (a newer version exists). `partial` is a normal outcome for scanned
documents, not an error page.

## First screens

1. documents/jobs list
2. document detail with original file and page images
3. extracted Markdown/JSON inspector
4. table, asset and chunk explorer
5. warnings, failures and retry actions
