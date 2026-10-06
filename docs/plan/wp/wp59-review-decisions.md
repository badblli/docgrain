# wp59-review-decisions — users answer conflicts; answers become approved data

- Özet: Kaynaklar aynı konuda farklı şey söylediğinde kullanıcıya soru olarak sor; verilen cevap onaylı değer olur ve yeni bir sürüm olarak yayınlanır. Şirket özeti sayıları da buradan gelir.
- Model: derin
- Phase: D4
- Branch: `codex/wp59-review-decisions` (base: `origin/dev`)
- Depends on: wp43, wp52 (merged)
- Role: implementer

## Goal

Merged revisions already keep conflicts (`_meta.conflicts`) and `needs_review` fields, but nothing lets a
person resolve them. Add a small write path: list open questions, answer one, publish a new immutable
revision in which that value is `accepted`. The web (wp60, in parallel) is built on the contract below —
keep it exactly.

## API contract (JSON, workspace-scoped, newest published revision unless `revision_id` given)

- `GET /v1/workspaces/{ws}/summary` →
  `{workspace_id, revision_id, documents, records, unsupported_fields, conflicts, needs_review,
    accepted_ratio, updated_at, collections: [{key, label, records, conflicts, needs_review}]}`
  (`label` = Turkish label if the schema has one, else the key; `accepted_ratio` 0..1 over fields.)
- `GET /v1/workspaces/{ws}/questions?limit=20&offset=0` →
  `{total, items: [{id, kind: "conflict"|"needs_review", collection, collection_label, record_id,
    record_title, field, field_label, lang, options: [{candidate_id, value, display, quote,
    document_name, locator}]}]}` — conflicts first, then needs_review; stable `id`
  (hash of revision lineage + record + field + lang) so a skipped question keeps its id.
- `POST /v1/workspaces/{ws}/questions/{id}/answer` with exactly one of
  `{"candidate_id": "..."}`, `{"value": <typed value>, "note": "..."}`, `{"skip": true}` →
  `{revision_id, remaining}`. A candidate answer marks that candidate `accepted` and the others
  `rejected`; a typed value adds a candidate with evidence `{kind: "user_edit", at, note}` (no quote —
  it is the person's authority, shown as "Sizin düzeltmeniz"); skip only reorders. Each non-skip answer
  writes a new merge revision (parent = previous id, history entry) and publishes it; old revisions stay
  readable. Concurrency: if the question's revision is no longer the newest, return 409.
- No answer may create a field without evidence: candidates keep their quotes; user edits carry
  `user_edit` evidence. `unsupported_fields` counts published fields with neither.

## Scope

- In: `apps/api/docgrain_api/` (records router/repository), `packages/records/` (revision update helper),
  `docker-compose.yml` (the records mount must become read-write), tests.
- Out: auth/users (record `actor: "local"`), web UI (wp60).

## Acceptance criteria

- [ ] `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass.
- [ ] Tests: summary counts; questions order and stable ids; candidate answer → approved mode now
      contains the value; typed edit → `user_edit` evidence; skip; 409 on stale revision; old revision
      still readable; no field without evidence after any answer.
- [ ] Report with example request/response bodies (synthetic data only).
