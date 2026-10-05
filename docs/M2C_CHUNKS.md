# M2c — Canonical structure-aware chunks

Chunking is an explicit derivation from stored canonical JSON; ingestion does not run this stage
automatically. Canonical data, latest/approved heads and parser outputs remain unchanged. The legacy
`/v1/chunks` and version counter APIs are not the revision-scoped canonical contract.

## HTTP contract

- `POST /v1/knowledge/revisions/{revision_id}/chunks`, body `{}` for defaults or a `ChunkingSpec`.
  Returns `{inserted, manifest}`. Identical publication is a no-op. A different config produces a
  separate derived revision. Bad config or no extractable content returns 422; missing source 404.
- `GET /v1/knowledge/revisions/{revision_id}/chunks?chunk_revision_id={derived_revision_id}`
  reads one explicit chunk run. Cross-revision, missing and historical lineage-only runs return 404.
- `GET /v1/knowledge/derivations/{derived_revision_id}/chunks/{chunk_id}` reads one actual chunk.
- Existing lineage API traces each chunk through all canonical context/source parents to the original
  processing/source revision. Demo mode rejects writes and never fabricates canonical chunk runs.

`ChunkingSpec` pins `canonical-structure` strategy version `1`, `unicode-characters` budget unit,
`max_chars` (default 1600), `max_table_rows` (default 20), caller-declared `table_header_rows` and
`include_entities` (default true). There is no embedding-model token count/limit in this version.

## Payload and source fidelity

Derived manifest 0.3.0 stores actual `chunks` and `chunk_omissions`. Prior schema files and manifests
are preserved. Chunks carry body `text`, contextualized `retrieval_text`, SHA-256, Unicode character
count, reading `order`, parent-local `ordinal`, context/source references, source slices and evidence.

- Container children define reading order. Consecutive text merges only within the same section/list
  context and role; tables and entities are separate. Original text is not trimmed. Oversized text
  splits at whitespace, then at character boundaries when necessary; `split_fallback` records this.
- Source text intervals refer to canonical TextBlock Unicode code points, not byte/PDF offsets.
  Original evidence retains page/bbox, DOCX path, TXT span or XLSX sheet/cell location. Context
  evidence and content evidence are separately inspectable; aggregate evidence includes both.
- Table JSON retains cell value/formula/cached value/display text/spans and caption. Row intervals
  are half-open canonical row indices. Headers repeat only when explicitly declared; default is zero.
  Each row stays intact even if it exceeds the budget; `oversized` is true. Formulas are not evaluated.
- Accepted schema-valid entities produce complete JSON chunks with all leaf field pointers/evidence.
  Pending/rejected/invalid/legacy entities and undescribed assets have explicit omission reasons.
  Disabling accepted entities is recorded as `entity_disabled`, not an acceptance failure.
- The soft budget includes context; long headings, rows, descriptions or entity JSON can overflow.
  No row/JSON truncation or fake token count. The repository recomputes the fixed strategy from the
  stored snapshot before publication, rejecting changed text, metadata, evidence or scope.

## Read-only example

```powershell
New-Item -ItemType Directory -Force data/reviews | Out-Null
$response = Invoke-RestMethod 'http://localhost:8000/v1/documents/doc_09ab90f4/knowledge'
$response.snapshot | ConvertTo-Json -Depth 100 | Set-Content -Encoding utf8 data/reviews/source.json
.venv/Scripts/python.exe docs/examples/preview_canonical_chunks.py `
  data/reviews/source.json data/reviews/m2c-chunks.json --max-chars 1600 --max-table-rows 20
```

Replace the local document ID for another dataset. This reads source JSON and writes a local preview;
no DB write, re-ingestion, LLM or embedding call. Older canonical 0.2.0 snapshots can be previewed
without rewriting source history. Actual automatic semantic entity extraction, tokenization/ranking,
chunk invalidation/indexing and product UI remain later capabilities.

See [ADR 0009](adr/0009-structure-aware-chunk-derivation.md).
