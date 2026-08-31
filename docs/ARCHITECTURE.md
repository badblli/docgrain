# Architecture Decision Record: Initial Direction

## Decisions

| Area | Initial decision | Why |
|---|---|---|
| Repository | Docker-first monorepo | API, worker and UI evolve together while sharing contracts. |
| API | FastAPI | Native Python ecosystem fit and OpenAPI support. |
| Worker | Durable queue worker backed by Redis | Extraction must survive API/container restarts. |
| UI | Next.js | Good operational console, server-side access control and rich document viewer support. |
| Primary parser | Docling | Structured document model and multi-format parsing. |
| Database | PostgreSQL | Transactional jobs, versions, metadata and full-text baseline. |
| Object storage | MinIO locally; S3/GCS-compatible in deployment | Keep large binaries outside the application database. |
| Vector index | Qdrant | Metadata filtering and independent vector lifecycle. |
| Vision | Pluggable Gemini/Qwen VL providers | Hosted quality and local/private choices. |

## Multimodal document understanding

Docgrain does not treat a document as a flat text stream. Text blocks, headings,
lists, tables, figures, diagrams, charts, forms, captions and page regions are
first-class structures. Docling produces the canonical structural extraction;
vision providers interpret only pages or regions selected by the quality gate.

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

Vision output is evidence-bound. Every derived observation records its source
page/region, related node identifiers, provider/model, prompt version,
confidence and purpose. Derived observations never replace canonical content.

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
7. Derived LLM content never overwrites canonical Docling extraction.
8. Every extracted table, asset and derived observation retains page/region provenance.
9. Every vision observation is evidence-bound and identifies its provider/model/prompt version.
10. Document-graph relationships are version-scoped and never point across tenants.
11. Multimodal chunks enumerate every text, table and asset source they inherit.
12. Heading structure is preferred over semantic splitting; cosine similarity and
    overlap are controlled fallbacks, not default flattening behavior.

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
