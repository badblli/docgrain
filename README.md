# Docgrain

**Structured knowledge from every document.**

Docgrain is a Docker-first, open-source document-ingestion service. It converts documents into reviewable, versioned, retrieval-ready knowledge while preserving the page, table, image, and section context that produced it.

It is designed to be used as a standalone service by products such as Luwi, rather than as a chatbot application itself.

> Project status: pre-alpha. The public API and data contract are being designed and may change.

## What Docgrain does

```text
Upload or connector source
  -> durable ingestion job
  -> parse, render and normalize
  -> enrich images, tables and page metadata
  -> create contextual chunks
  -> optionally embed and index
  -> expose reviewable artifacts and a document manifest
```

Docgrain stores the original file, page renders, extracted Markdown, structured document JSON, extracted assets, tables, and chunk manifests. A consuming application can then decide how it wants to search or answer over those artifacts.

## Why it exists

Most RAG prototypes flatten a PDF to plain text and lose the layout, page source, tables, images, and version history needed for reliable production use. Docgrain treats extraction as a durable, inspectable pipeline.

The goals are:

- support PDF first, then DOCX, PPTX, XLSX, HTML and more;
- preserve provenance from a chunk back to document version, page, section, table and image;
- make every pipeline stage observable and retryable;
- keep provider choices replaceable (Docling, Gemini, Qwen, embeddings, storage, indexes);
- offer a practical web UI for quality review, not only an API;
- remain useful without a built-in chat experience.

## Product boundaries

Docgrain owns ingestion, artifact generation, metadata, versioning, optional indexing, and document review. It does **not** own end-user chat, prompt policy, conversation history, or business-domain answer generation.

```text
Luwi or another consumer
        |
        | document upload / source registration / job status / manifest
        v
     Docgrain
        |
        +-- original source and document artifacts
        +-- chunk manifest and optional index records
```

## Core pipeline

1. **Register** -- validate the source, calculate a content hash, create a document version and queue a durable job.
2. **Render** -- render PDF pages to PNG previews. Preserve the original file; use higher resolution only for difficult vision work.
3. **Extract** -- use Docling as the primary parser to produce structured JSON and canonical Markdown.
4. **Quality gate** -- detect empty, suspiciously short, low-confidence, scanned, table-heavy, or layout-complex pages.
5. **Vision fallback/enrichment** -- send only qualifying pages to a configured vision provider. Gemini is the hosted quality profile; Qwen VL is an optional local/private profile.
6. **Normalize** -- repair safe formatting defects without replacing source content. Keep original and normalized variants.
7. **Chunk** -- split by document and heading structure; apply token-aware fallback splitting only when necessary.
8. **Enrich** -- attach contextual headers and inherited metadata to each chunk.
9. **Embed and index** -- optional provider-backed embeddings plus vector and keyword index writes.
10. **Publish** -- write an immutable manifest; mark the version `done`, `partial`, or `failed`.

## Visual and table extraction

Images and tables are first-class artifacts, not discarded during text extraction.

- Every PDF page can have a PNG render for UI review and source attribution.
- Tables are stored in structured JSON and Markdown/HTML representations where extraction supports it.
- Images retain page number, bounding box when available, MIME type, checksum, and storage URI.
- A vision provider may generate an image/table description, but the generated description is explicitly marked as derived content.
- Chunks reference their related `asset_ids` and `table_ids`; consumers can surface the exact source beside a retrieved result.

## Data contract

The relationship below is the non-negotiable backbone of the project:

```text
Workspace/Tenant
  -> Document
    -> DocumentVersion
      -> Page
        -> Asset | Table | Section
      -> Chunk
        -> Embedding | IndexRecord
```

Every chunk must include at least:

```json
{
  "id": "chk_...",
  "document_id": "doc_...",
  "document_version_id": "dver_...",
  "workspace_id": "ws_...",
  "text": "...",
  "embedding_text": "Document title > section path\\n\\n...",
  "heading_path": ["Title", "Section"],
  "page_numbers": [4, 5],
  "source_uri": "s3://.../original.pdf",
  "page_image_uris": ["s3://.../pages/0004.png"],
  "asset_ids": [],
  "table_ids": [],
  "access_scope": "workspace",
  "metadata": {}
}
```

## Chunking policy

Docgrain is heading-first, not fixed-window-first.

1. Keep a small document or coherent section as one chunk.
2. Split larger sections by subheading.
3. Merge orphan fragments below a configurable minimum size.
4. Use token-aware splitting with a small overlap only for large, headingless prose.
5. Keep page markers and inherited metadata in every output chunk.

Cosine similarity can help identify semantic boundaries in unstructured text, but it should not erase explicit document structure. Generic character overlap splitters are a fallback, not the primary strategy.

## Provider architecture

Provider interfaces prevent the rest of the pipeline from being locked to a model or cloud:

- `DocumentParser`: Docling primary parser
- `PageRenderer`: PyMuPDF or equivalent
- `VisionProvider`: Gemini, Qwen VL, or another compatible backend
- `EmbeddingProvider`: hosted or local embeddings
- `ObjectStorage`: S3, GCS, Azure Blob, or MinIO
- `VectorIndex`: Qdrant or pgvector
- `KeywordIndex`: PostgreSQL full-text initially; OpenSearch later if required

## Web application

The Next.js UI is an operations and quality-review console:

- upload/source registration and job tracking;
- original document and page-render viewer;
- extracted Markdown and structured JSON inspector;
- table and asset preview;
- chunk explorer with heading/page/source links;
- model/provider usage, warnings, failures and retries;
- version comparison and re-ingestion controls.

## Repository layout

```text
apps/
  api/                    FastAPI HTTP API
  worker/                 durable queue consumers and pipeline runners
  web/                    Next.js review console
packages/
  domain/                 models, state machine, metadata contract
  pipeline/               extraction, rendering, normalization, chunking
  providers/              Docling, Gemini, Qwen, storage and index adapters
  indexing/               embedding, vector/keyword index coordination
  observability/          logging, metrics and tracing helpers
infra/
  docker/                 container build definitions
  compose/                local development configuration
docs/                     architecture, ADRs, API and contributor guides
tests/                    fixtures, unit, integration and end-to-end tests
```

## Local development

The initial stack is Docker Compose based:

```bash
cp .env.example .env
docker compose up --build
```

Services planned for the local environment:

- Next.js web application
- FastAPI API
- Python worker
- PostgreSQL
- Redis
- MinIO
- Qdrant

## Public project principles

- No credentials, customer documents, generated indexes, or real production data in Git.
- Reproducible local environment through Docker Compose.
- Golden document fixtures for PDFs, scans, tables, images and multilingual content.
- Every feature needs tests around provenance and metadata preservation.
- Keep API and metadata-contract changes documented in an ADR or migration note.
- Providers are optional integrations; core document models remain vendor-neutral.

## Roadmap

### Milestone 0 -- foundation

- [ ] Docker Compose stack and health checks
- [ ] document/job/version data model
- [ ] PDF upload, original-file storage, page PNG rendering
- [ ] Docling extraction to Markdown + JSON
- [ ] web document and artifact viewer

### Milestone 1 -- retrieval-ready output

- [ ] heading-aware chunker and manifest
- [ ] asset/table metadata links
- [ ] embeddings, Qdrant, keyword index
- [ ] provider adapters and retry policy
- [ ] partial job handling and re-ingestion

### Milestone 2 -- quality and scale

- [ ] vision fallback and derived captions
- [ ] document version comparison
- [ ] tenancy and access scopes
- [ ] observability dashboard and evaluation suite
- [ ] connectors for URLs and cloud storage

## Inspiration and acknowledgements

Docgrain draws inspiration from practical open-source RAG work such as [paper-bold](https://github.com/enesmanan/paper-bold) and [DataCommit](https://github.com/enesmanan/DataCommit), while expanding their prototype-level pipelines into a standalone, inspectable document-ingestion service. It will use [Docling](https://github.com/docling-project/docling) as the primary document-processing foundation.

## License

This repository is licensed under the MIT License. See [LICENSE](LICENSE).
