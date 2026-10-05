# wp43-records-json-api — Shared record exports and read access

- Özet: Onaylanan bilgi listelerini web, mobil ve yapay zekâ için aynı sürümlü yayından sun.
- Model: standart
- Phase: D5
- Branch: `codex/wp43-records-json-api` (base: `origin/dev` after dependency review)
- Depends on: wp41-record-extractor, wp42-record-merge
- Role: implementer
- Owner: Porygon / cem

## Goal

Web/mobile JSON and compact AI context derive from the same accepted KnowledgePack revision.
Consumers can read stable records, their translations and source links without model calls.

## Scope

- In: records export module, `apps/api/docgrain_api/`, API/unit tests, neutral API examples.
- Out: web UI, write/review endpoints, embeddings, model calls, webhooks, auth redesign.

## Tasks

1. Read existing KnowledgePack publication/storage conventions before adding record artifacts.
   Export `rooms.json`, `outlets.json` and other hospitality collections with an explicit schema
   version, workspace/revision ids, stable Record ids, i18n and field-level Evidence.
2. Export only accepted records/fields; omit proposed, rejected and unresolved conflicting
   values. Keep accepted unrelated fields usable; document the precise publication rule.
3. Add read-only collection list/detail and record detail routes under the existing workspace
   boundary. Support explicit published revision; distinguish empty, unknown and unpublished.
4. Add ETag/If-None-Match support derived from immutable revision/artifact content; prevent
   mixing workspaces or revisions. Do not overwrite or regenerate old published artifacts.
5. Precompute compact context from these same accepted records during export; preserve source
   references and EN-first/i18n semantics. Serve it without extraction or external calls.
6. Test JSON/context parity, ReviewState filtering, conflicts, translations, old revision reads,
   ETag 304 and cross-workspace misses. Document a local read example and preparation timings.

## Acceptance criteria

- [ ] Repo venv `python -m pytest -q tests/unit/test_records_export.py tests/unit/test_records_api.py` passes.
- [ ] Repo venv `python -m ruff check apps/api packages/records tests/unit/test_records_export.py tests/unit/test_records_api.py` passes.
- [ ] JSON and context expose identical accepted facts and revision; all values retain Evidence.
- [ ] Proposed/rejected/unresolved values are absent; EN primary and i18n survive export/read.
- [ ] Routes are read-only; unknown/foreign workspace or revision cannot return another pack.
- [ ] Same artifact gives 304 with matching ETag; changed revision changes ETag; old reads persist.
- [ ] Report reproducible direct-context preparation p95 on a named synthetic fixture and hardware;
  target <100 ms, with at least 100 measured reads after warm-up, excluding model response time.
- [ ] No default model/network calls; synthetic tests only; report unavailable worker integrations.

## Notes

Read `docs/plan/ROADMAP.md`, `docs/plan/wp/wp21-compact-context.md`, wp41 and wp42.
This is a D5 slice; two-model D1 evaluation remains a separate gate, not implied by API tests.
