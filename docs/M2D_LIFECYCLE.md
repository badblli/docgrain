# M2d — Canonical diff and incremental index lifecycle

Canonical JSON remains authoritative. M2d implements the programmatic worker lifecycle and
read-only HTTP inspection. Automatic ingestion wiring, live model adapters, Qdrant writes and
search ranking are separate milestones. See [ADR 0010](adr/0010-canonical-diff-incremental-lifecycle.md).

## Diff and invalidation

`canonical_diff(before, after)` compares objects by collection/logical ID. Changes include
exact RFC6901 content paths and annotation/evidence metadata paths. Reordering the physical
node list has no effect; container child order does. New anchors are additions/removals, not
fuzzy matches. Workspace/document mismatch fails. Source/processing-only changes do not
invent object edits, but chunk occurrences are rebuilt with the target revision's evidence.

`invalidated_descendants(diff, registered_graph)` walks all reachable edges without the public
trace endpoint's result cap. This is a conservative candidate set. `plan_chunks` regenerates
pure deterministic chunks and compares logical IDs/content digests to report `reuse`, `embed`,
`delete` and `metadata_refresh`. Actual embedding cache reuse can also cover new logical IDs
with identical retrieval text. This plan does not predict provider calls or model token budgets.

## Execution boundary

```python
from docgrain_api.index_repository import IndexRepository
from docgrain_domain.canonical.indexing import EmbeddingSpec, IndexSpec
from docgrain_worker.index_lifecycle import refresh_index

# connect is a configured psycopg connection factory; adapter is supplied by the caller.
repository = IndexRepository(connect)
repository.initialize()  # additive local-development DDL
spec = IndexSpec(name="default", embedding=EmbeddingSpec(
    provider="your-provider", model="your-model", version="pinned-version", dimensions=768))
generation, inserted = refresh_index(repository, canonical_revision_id, spec, adapter,
                                     expected_generation_id=active_generation_id)
```

`adapter.embed(retrieval_text, embedding_spec)` must honor every pinned setting and return the
configured number of finite numeric values. There is no default model or fixture fallback.
Checkpoints are scoped by workspace/document/embedding specification/text checksum. Changed
model/version/dimensions/options create a new cache identity. Unicode character chunk limits
are not a model token guarantee; the adapter must enforce its real input constraints.

Builders serialize per document with a PostgreSQL advisory lock. Successful embeddings are
checkpointed immediately in independent transactions. Failed builds retain checkpoints and
the old active head. A retry skips checkpoints and returns an existing successful generation
without embedding or rewinding a newer head. A crash between a provider response and its
checkpoint can repeat that provider request; exactly-once external calls are not promised.

Publication verifies canonical chunks and scoped checkpoints, checks latest canonical revision,
then writes the complete immutable generation and switches the named document index head in
one transaction using expected base generation CAS. Readers fetch head + complete payload in
one SQL statement. Deleted entries disappear from the active payload; historical generations
remain immutable. An empty `ChunkSet` can publish zero entries and remove all prior knowledge.
Historical `DerivedManifest` remains nonempty and its serialized hashes/schemas are preserved.

`full=True` regenerates all vectors/entries and bypasses cache reads. The adapter's pinned
configuration must produce the same immutable vector; different output is a conflict and needs
a new version. Full rebuild repairs incomplete generations, not arbitrary mutation of history.
Generation 0.1.0 has its own generated JSON Schema. Its nonempty chunk/embedding/index
manifests participate in the existing registered lineage graph, with revision-qualified edges.

## Read-only HTTP

- `POST /v1/knowledge/revisions/{to_revision_id}/diff`, body `{"from_revision_id":"..."}`
  returns `{diff, invalidated_candidates}`.
- `POST /v1/knowledge/revisions/{to_revision_id}/index-plan`, same body plus optional
  `chunking` and `previous_chunking` specifications, returns the chunk plan.
- `GET /v1/knowledge/documents/{document_id}/indexes/{index_name}?workspace_id=...`
  reads one complete active generation. Missing/scoped-out results return 404.

These routes never embed or publish. Demo mode returns 404 rather than fake canonical data.
Missing revision is 404; invalid spec/cross-document comparison is 422. Existing live legacy
version diff remains a counter comparison. There is no unauthenticated HTTP vector writer.

## Reproducible preview and tests

```powershell
$env:PYTHONPATH = 'packages/domain'
python docs/examples/m2d_diff_preview.py snapshot.json counterfactual-diff.json
python -m pytest tests/unit/test_m2d_lifecycle.py -q
# PostgreSQL integration uses a unique temporary schema; real Docling requires worker deps.
python -m pytest tests/integration/test_m2d_index_lifecycle.py -q
```

The preview explicitly labels simulated cell/row/provenance edits; source files and stored
revisions are unchanged. Tests inject a deterministic test-only embedder, provider/SQL failures
and concurrency; real TXT/XLSX edits are parsed into new verified source revisions in isolated
schemas. No paid model calls, user-document re-ingestion or live index writes are needed.
