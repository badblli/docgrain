# Architecture Decision Record: Initial Direction

## Decisions

| Area | Initial decision | Why |
|---|---|---|
| Repository | Docker-first monorepo | API, worker and UI evolve together while sharing contracts. |
| API | FastAPI | Native Python ecosystem fit and OpenAPI support. |
| Worker | Durable queue worker backed by Redis | Extraction must survive API/container restarts. |
| UI | Next.js | Good operational console, server-side access control and rich document viewer support. |
| Primary extractor | Gemini Vision behind `VisionProvider` | Every rendered page is read multimodally, including text, tables, images and layout. |
| Structural parser | Docling | Deterministic secondary parse for validation, reconciliation and fallback. |
| Database | PostgreSQL | Transactional jobs, versions, metadata and full-text baseline. |
| Object storage | MinIO locally; S3/GCS-compatible in deployment | Keep large binaries outside the application database. |
| Vector index | Qdrant | Metadata filtering and independent vector lifecycle. |
| Vision alternatives | Pluggable Qwen VL or compatible providers | Keep hosted quality and local/private deployment choices. |

## Multimodal document understanding

Docgrain does not treat a document as a flat text stream. Text blocks, headings,
lists, tables, figures, diagrams, charts, forms, captions and page regions are
first-class structures. Every rendered page is sent to the configured primary
vision provider with bounded concurrency and retries. The page join step builds
the normalized document representation; Docling supplies a secondary,
deterministic parse used for validation, reconciliation and fallback.

The normalized representation is a document graph:

```text
DocumentVersion
  -> Page
    -> Section | TextBlock | Table | Asset | Form
  -> Relationship
    -> described_by | references | continues_on | belongs_to | sourced_from
  -> Chunk
    -> text + related tables/assets + inherited context
```

Graph nodes retain page and bounding-box provenance. Relationships make such
facts as a figure's caption, a table continued on the next page, or a paragraph
referencing a diagram queryable without flattening the original layout.

Vision output is evidence-bound. Accepted OCR, layout and table extraction can
be published as canonical normalized extraction while retaining provider/model,
prompt version, confidence and source-region metadata. Semantic descriptions,
summaries and inferred relationships remain `derived`; they never masquerade as
literal source content.

Chunks may be multimodal: coherent text can be packaged with a table summary,
figure description and section context. The chunk still points to every
canonical and derived component used to construct it.

## Job state machine

```text
queued -> rendering -> extracting -> quality_check -> enriching
       -> chunking -> embedding -> indexing -> done
                                  \-> partial
any non-terminal state -> retrying -> previous state
any non-terminal state -> failed
```

A `partial` version is searchable only for successfully produced chunks and retains a page-level failure report. A failed version does not replace the latest completed version.

## Invariants

1. Original source files are immutable.
2. A new content hash creates a new document version; it never mutates historical artifacts.
3. Chunks never cross workspace/tenant boundaries.
4. Every chunk has a document version and at least one provenance anchor.
5. Index writes are idempotent and keyed by document-version/chunk identifiers.
6. A document version is published only after the manifest is complete.
7. The immutable source and page renders remain the ultimate evidence; accepted
   normalized extraction never destroys an earlier extraction variant.
8. Every extracted table, asset and derived observation retains page/region provenance.
9. Every vision observation is evidence-bound and identifies its provider/model/prompt version.
10. Document-graph relationships are version-scoped and never point across tenants.
11. Multimodal chunks enumerate every text, table and asset source they inherit.
12. Heading structure is preferred over semantic splitting; cosine similarity and
    overlap are controlled fallbacks, not default flattening behavior.
13. Every rendered page is submitted to the configured primary vision extractor;
    page retries are bounded and exhausted pages produce a `partial` version.
14. Interpretive vision content is `derived`, even when accepted OCR/layout
    extraction contributes to the canonical normalized representation.

## API outline

```text
POST   /v1/documents                    register/upload a document
GET    /v1/documents/{document_id}      document and latest version
GET    /v1/versions/{version_id}        version, artifacts and warnings
GET    /v1/jobs/{job_id}                pipeline status
POST   /v1/versions/{version_id}/retry  retry a failed/partial stage
GET    /v1/chunks/{chunk_id}            chunk and provenance
```

Authentication, tenancy and signed file upload URLs are required before any production deployment.
