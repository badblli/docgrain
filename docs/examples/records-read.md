# Sürümlü kayıtları okuma

WP43 adds a separate local KnowledgePack record publication adapter. Existing
document `canonical.json`, `ai.json`, `context.md`, manifests and S3 publications
are unchanged. No read extracts content, projects records, downloads sources or
calls a model. Configure `RECORDS_PUBLICATION_ROOT` on the API with the same local
directory used by the offline publisher; it is empty (disabled) by default.
This adapter requires a shared local filesystem if API processes run separately.
PostgreSQL/MinIO record publication and automatic worker integration are not
implemented in this D5 slice.

## Publication rule

The lead's two-mode rule applies to the same pinned merge revision:

- `preview` is the default. Every non-rejected, single-candidate field is visible
  with its original `proposed`, `needs_review` or `accepted` state and Evidence.
  If a language has one accepted candidate it wins; otherwise multiple non-rejected
  candidates form an explicit conflict. The lowest candidate ID supplies the
  display value without becoming accepted. All alternatives remain inspectable
  under `_meta.conflicts`. A record's `_meta.review_state` is `needs_review` if
  any field or translation needs review; otherwise `proposed` if any is proposed;
  otherwise `accepted`. Each field has its own state in `_meta.fields`.
- `approved` includes only explicitly accepted field/language candidates.
  Unaccepted conflicts, proposed/needs-review singles and rejected values are
  absent. A record with no accepted values is absent.
- Both modes preserve English as the first choice per field, then
  English regional variants, then a deterministic evidenced language fallback.
  `?lang=tr` selects available Turkish per field; missing translations fall back
  to English, then the available language. Unknown languages use default English
  artifacts. Non-English translations retain field-level Evidence in `_meta.fields`.
- Collection JSON is a plain array: `id`, plain field values, `i18n`, `_meta`.
  Provenance occurs only under `_meta`; filenames include `rooms.json`,
  `outlets.json`, `activities.json`, `facilities.json`, `policies.json`,
  `contacts.json`, `properties.json`, `service_prices.json`.
  Manifest and HTTP headers identify schema `1.0.0`, workspace and revision.
  Immutable files live in `published/preview/` and `published/approved/`.
- Compact Markdown comes from these same projected arrays, including translations,
  explicit `Kaynaklar çelişiyor: A (belge X) / B (belge Y)` lines and a deduplicated
  source-key map with full Evidence/source-version/knowledge-revision pins.
  Source strings are JSON-quoted data; no source text is promoted to instructions.

## Workspace-discovered collections (WP52)

Pass the accepted `schema.v<N>.json` to extraction with `--schema`. Extraction
compiles its reviewed field types into strict models; it scans each section and
runs a completeness pass for every discovered collection. Collection definitions
and source examples remain untrusted data. No model runs without explicit
`--base-url`, `--model` and `--api-key-env` configuration.

```powershell
$python = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
$env:PYTHONPATH = 'apps/api;packages/domain;packages/records;packages/evaluation'
& $python -m docgrain_records extract --schema <schema.v1.json> --document <document-id> --api http://127.0.0.1:8000 --dry-run
& $python -m docgrain_records extract --schema <schema.v1.json> --document <document-id> --api http://127.0.0.1:8000 --base-url <compatible-endpoint> --model <model> --api-key-env MODEL_API_KEY --out <records/document-id>
& $python -m docgrain_records match --records <records> --schema <schema.v1.json> --out <matches>
& $python -m docgrain_records merge --records <records> --schema <schema.v1.json> --matches <matches/match_proposals.json> --out <merged>
```

Matching emits review proposals. Explicit reviewed matches or the existing
`--auto-accept strong` rule are required to join records; neither accepts field
values. Matching and merging also read the schema snapshot from `records.json`
when `--schema` is omitted. Mixed workspace/schema versions fail closed.
If a collection has `name`, it identifies records. Otherwise its first accepted
field is the identity, and requires evidence. This fallback supports collections
such as classes with `title`; keep a distinguishing field first during review.
Record metadata names (`id`, `type`, `i18n`, `review_state`, `conflicts`, `_meta`)
cannot be collection fields. Numeric schema fields participate in matching even
when their names differ from hospitality examples.

Publish `<merged/merge_revision.json>` with the preparation helper below.
Each discovered key gets `<key>.json` and `<key>.context.md` in both modes.
Only that workspace's collections appear in the manifest and read API. Dynamic
rows identify workspace, merge revision and accepted schema version under `_meta`.
The merge revision preserves the full accepted schema snapshot, so old reads
remain tied to that version after a new discovery. Verified quotations, immutable
source-version/revision pins, explicit conflicts, language fallback and ETags
follow the publication rules above. Without `--schema`, extraction uses the
hospitality compatibility fixture through the same model-generation path.

## Hospitality example preparation and reads

From the worktree, in PowerShell (repo venv):

```powershell
$python = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
& $python docs/examples/records_read.py --root storage/records
$env:RECORDS_PUBLICATION_ROOT = (Join-Path (Get-Location) 'storage/records')
$env:PYTHONPATH = 'apps/api;packages/domain;packages/records'
& $python -m uvicorn docgrain_api.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
$base = 'http://127.0.0.1:8000/v1/workspaces/workspace-synthetic/revisions/synthetic-rooms-200-v1/collections'
Invoke-RestMethod $base
Invoke-RestMethod "$base/rooms"                # preview
Invoke-RestMethod "$base/rooms?mode=approved"  # accepted only
Invoke-RestMethod "$base/rooms/records/rec-0?lang=tr&mode=preview"
$read = Invoke-WebRequest "$base/rooms/context"
Invoke-WebRequest "$base/rooms/context" -Headers @{ 'If-None-Match' = $read.Headers.ETag }
```

The final request returns 304 (PowerShell versions may surface it as an exception).
Every route is GET-only. Explicit revision is required; there is no mutable latest
alias. Known empty collections return `200 []`; unknown workspace/revision/collection/
record returns 404; staged but unpublished revisions return 409. Checksummed artifact
corruption/unavailability returns 503. Workspace/revision checks precede conditional
GET. ETags hash workspace, revision, mode and representation bytes; weak tags, tag lists
and `*` are supported. Old published files are never overwritten or regenerated.
The existing application's authentication model is unchanged; path scoping is not
a new tenant authorization system.

For reviewed wp42/wp47 data, pass its aggregate `merge_revision.json` (alongside
the per-collection internal files), never the collection display views as authority:

```powershell
& $python docs/examples/records_read.py --root storage/records --revision-file <path-to-merge_revision.json>
```

The loader discards computed `primary/i18n/conflicts/review_state` field views;
candidate review states and Evidence pins remain authoritative. It never accepts
fields implicitly. The helper prints counts of rooms with name/capacity in each
mode without printing source content. `RecordsRepository.stage`
can prepare an unpublished revision; `publish` atomically exposes a fully written
directory and manifest. IDs are hashed for filesystem paths, preventing traversal.

## Reproducible preparation measurement

```powershell
& $python docs/examples/records_read.py --root storage/records-benchmark-final
```

Fixture: `synthetic-rooms-200-v1`, 200 room records, three accepted fields each.
20 warm-up reads followed by 200 measured reads, nearest-rank p95. Each preparation
reads manifest and context from disk, validates workspace/revision and SHA-256,
and decodes UTF-8. Disk/OS caching is allowed after warm-up. Publication time, model
response time and HTTP transport are excluded. Hardware and final measurements
are recorded below after running the command. This is a D5 preparation benchmark,
not the separate two-model D1 evaluation gate.

Measured 2026-10-06: AMD Ryzen 5 5600X 6-Core Processor (AMD64 Family 25,
Model 33, Stepping 2), Windows 11 build 26200, Python 3.12.5. Context length:
140,138 characters; median **0.800 ms**, p95 **1.093 ms**, below 100 ms.
These numbers describe local stored context preparation only.

The 2026-10-06 offline read of wp47 `merge_revision.json` produced these counts
without printing source content: `preview` **10 rooms**, **10 with name**, **7 with
capacity**; `approved` **0 rooms** (no accepted fields in that revision).
