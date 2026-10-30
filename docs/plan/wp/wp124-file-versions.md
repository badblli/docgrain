# wp124-file-versions — Upload a new version of a document and see what changed

- Özet: Bir belgenin yeni halini aynı belgenin "yeni sürümü" olarak yükleyebilelim ve iki sürüm arasında yalnızca değişen paragraf, tablo hücresi ve başlıklar listelensin; tek kelimelik bir DOCX değişikliği tek bir değişen parça olarak görünsün.
- Model: derin
- Engine: codex
- Phase: D3
- Branch: `codex/wp124-file-versions` (base: `origin/dev`)
- Depends on: none
- Role: implementer
- Owner: Charizard (codex)

## Why (lead reading, 2026-10-30)

D3 is the user's original pain ("bir kelime değişikliği için tüm belgeyi tekrar işleyemem") and it is not built:

- `apps/api/docgrain_api/routers/documents.py` `_register_document` always creates a **new document**
  (`version_count=1`, `revision=1`). There is no way to say "this file is the new version of document X". The data
  model already has versions (`Document.latest_version_id`, `DocumentVersion.revision`, `/documents/{id}/versions`)
  and the records job already reads `latest_version_id` (`records_jobs.source_snapshot`).
- `routers/versions.py` `diff` returns **count deltas only** (pages/chunks/tables/assets). Nothing tells a person
  which paragraph or cell changed.
- `packages/domain/docgrain_domain/canonical/incremental.py` `canonical_diff` compares canonical objects **by id**.
  Check whether ids are stable across two versions of the same file; content-derived ids would make every edited
  block look like removed + added.

## Read first

`routers/documents.py` (register/upload/confirm, sha256 dedup, WP108 failed-job requeue), `routers/versions.py`,
`routers/incremental.py`, `routers/knowledge.py` (`latest_knowledge`), `packages/domain/.../canonical/incremental.py`,
the repository used by these routers, `apps/worker/docgrain_worker/main.py` (what a document job produces and where
the Docling document JSON is stored), `packages/records/docgrain_records/structure_units.py` (how we already walk
Docling JSON: tables, cells, headings, list items, locators), docs/adr/0024-docling-reads-documents.md.

## Goal

1. **New version upload** — `POST /v1/documents/{document_id}/versions` with the same register payload shape
   (filename, mime type, byte size, sha256). It creates `DocumentVersion(revision = previous + 1)` and a job in the
   **same** document and workspace, returns the same `RegisterResponse` (upload URL, job id), and the existing
   `PUT .../content` + `POST .../uploaded` steps work unchanged.
   - Same sha256 as the current latest version → `deduplicated=True`, no new version.
   - Different format family than the document (e.g. PDF → XLSX) → 415; a renamed file of the same format is
     allowed (store the new filename on the version; keep the document title).
   - `latest_version_id` moves to the new version **only when its job finished usable**; while it is preparing or
     after it failed, the previous version stays the latest for records/AI (no half-read document ever replaces a
     good one). Expose the pending version in `/documents/{id}/versions` with its status.
   - Old versions, their artifacts and knowledge revisions stay readable.
2. **Change list between two versions** — replace the count-only live response of
   `GET /v1/versions/{version_id}/diff?base=...` (keep the fixture path) with a block-level diff computed from the
   two Docling documents:
   - units: headings, paragraphs/list items, table cells (row + column header labels as the address), key-value
     items, picture text;
   - each change: `operation` added/removed/changed, `kind`, `address` (heading path, table name + row/col headers),
     `before` / `after` text, locators (page/bbox or Docling ref) for both sides;
   - matching is by structure address first, then by normalized text similarity, so an edited paragraph is one
     `changed` item, not removed + added; moved-but-equal blocks are not changes; whitespace/Unicode normalization
     differences are not changes;
   - also return counts (keep the old count fields for compatibility) and `unchanged_units`.
   Put the algorithm in a pure module (e.g. `packages/domain/docgrain_domain/canonical/version_diff.py`) with no I/O.
3. **Machine-readable output for WP125** — the diff result must let the records job decide per document whether
   anything changed, and which units/locators changed. Document the shape in the module docstring.

## Scope

- In: `routers/documents.py`, `routers/versions.py`, repository methods they need, the new pure diff module, tests,
  `docs/` API notes.
- Out: records/collections behaviour (WP125 works in `records_jobs.py`, `records_pipeline.py`,
  `packages/records/` — do not touch those), web UI (later WP), webhooks (D6).

## Rules

Never delete replaced code: the old count-only diff stays, marked `KULLANILMIYOR (karar 18)`. No network, no Git,
no builds. Synthetic test documents only (no customer names). No model calls.

## Acceptance criteria

- [ ] API tests: new version of an existing document → `revision=2`, same document id, previous version still the
      latest until the job is usable, then switched; same sha → deduplicated; format family change → 415; failed new
      version leaves the old one as latest.
- [ ] Diff tests on synthetic Docling JSON (and, where the image is available, real DOCX via Docling):
  - one word changed in one paragraph of a DOCX → exactly **1** `changed` item with before/after text;
  - one table cell price changed → 1 `changed` item addressed by row + column header;
  - a paragraph added and one removed → 1 added + 1 removed;
  - identical content re-saved (different bytes, same text) → 0 changes;
  - two equal paragraphs swapped → 0 changes.
- [ ] `.venv/Scripts/python -m pytest -q` green, `.venv/Scripts/python -m ruff check .` clean.
- [ ] Report in Turkish: whether canonical ids are stable across versions, the diff shape, and the lead's live
      commands (upload v1, upload v2 with one word changed, read the diff).

## Notes

Parallel with WP125 (Porygon). WP125 will call the diff module; agree only on the module's public function and
result model, written in its docstring. The lead rebuilds Docker and runs the live DOCX check after merge.
