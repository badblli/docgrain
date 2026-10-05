# M2b — External schemas, entities and field evidence

Canonical 0.4.0 adds `SchemaEntity`; historical snapshots remain readable.
Schema registration, candidate publication and review are explicit API operations.
An upload does not automatically infer business entities in this milestone.

## API lifecycle

1. `POST /v1/schemas`: register `{workspace_id, reference: {id, version, content_sha256}, document}`.
   The SHA-256 pins canonical JSON bytes of the supplied schema. Repeating the same registration
   is a no-op; different content under the same workspace/ID/version returns 409. Only Draft
   2020-12 with local references and supported formats is accepted. Defaults do not fill values.
2. `GET /v1/schemas/{schema_id}/versions/{version}?workspace_id=...`: read the pinned schema.
3. `POST /v1/knowledge/revisions/{revision_id}/entities`: publish an `EntityBatch` with a pinned
   `schema_ref`, explicit `producer` and candidate `entities`. Candidates carry identity key, type,
   label, JSON `data`, overall annotation and `field_annotations` keyed by RFC 6901 pointers.
   Every JSON leaf requires evidence from that snapshot. Confidence needs a method when supplied.
   Publication requires an M2a processing revision; legacy 0.2.0 must be reprocessed first.
4. `GET /v1/knowledge/revisions/{revision_id}/entities`: inspect stored schema entities.
5. `POST /v1/knowledge/revisions/{revision_id}/entities/{entity_id}/reviews`: send a decision with
   `decision_id`, `from_status`, `to_status`, `reviewer_id`, `reason` and timezone-aware `occurred_at`.
   Allowed chain: `extracted → needs_review → accepted/rejected`. Invalid data cannot be accepted.
   Each decision returns a new canonical snapshot; use that revision ID for the next decision.
   Repeating an identical operation against the same base is a no-op. Conflicting heads return 409.
6. `POST /v1/knowledge/revisions/{revision_id}/entities/{entity_id}/projection`: an accepted entity
   produces a separate derived 0.2.0 manifest with JSON text, checksum and canonical entity lineage.
   `GET /v1/knowledge/derivations/{id}` reads it. Canonical `data` is never modified by projection.

Schema version migration requires an explicit future policy; one snapshot cannot silently mix
versions of a logical schema. Correcting entity data starts a new extraction/review cycle while
preserving logical entity identity. Approval of a whole revision requires all schema entities accepted.
Repository workspace/evidence scope is checked; caller authentication is outside this milestone.
Demo mode rejects writes and does not fabricate entities.

## Read-only table mapping example

Install domain and API packages in the local environment (see the development harness), then run:

```powershell
# Save only the snapshot from a real read-only knowledge response.
$result = Invoke-RestMethod 'http://localhost:8000/v1/documents/doc_09ab90f4/knowledge'
New-Item -ItemType Directory -Force data/reviews | Out-Null
$result.snapshot | ConvertTo-Json -Depth 100 | Set-Content -Encoding utf8 data/reviews/source.json
.venv/Scripts/python.exe docs/examples/map_table_entities.py `
  data/reviews/source.json docs/examples/service.schedule.v1.schema.json data/reviews/m2b-preview.json `
  --schema-id service.schedule.v1 --entity-type service_schedule `
  --table-id table_27b101c500a5d260a527efbe4d4b5cad --identity-field service `
  --field service=0 --field hours_text=1 --field venue=2 --skip-rows 0 --limit 6
```

This example explicitly selects six F&B rows from the local XLSX. Table/document IDs are local
acceptance data and must be replaced for another dataset. The schema and bindings are caller inputs;
there is no business class in core. `hours_text` preserves the source spelling, spacing and overnight
notation; interpreting times requires a later explicit normalization policy. Each entity remains
`extracted`, awaiting review. Output includes the candidate batch, schema-valid entities and original
sheet/cell evidence. No publication, re-ingestion, schema discovery or LLM call occurs.

Architecture rationale: [ADR 0008](adr/0008-schema-entities-field-provenance.md).
