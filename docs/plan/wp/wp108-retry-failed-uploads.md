# wp108-retry-failed-uploads — Re-uploading a file whose last job failed must process it again

- Özet: Aynı dosya yeniden yüklendiğinde, daha önceki işi başarısız olmuşsa eski başarısız sonuç kopyalanmasın; dosya yeniden işlensin.
- Model: standart
- Engine: agy
- Phase: D18
- Branch: `codex/wp108-retry-failed-uploads` (base: `origin/dev`)
- Depends on: none
- Role: implementer
- Owner: Bulbasaur (agy)

## Why (lead, 2026-10-09)

Folder ingest asks the API to reuse persisted content hashes. A JPEG whose job had been marked `failed` (worker
crash) was re-uploaded after the fix and the API reused the failed job (`reused: true`, status `failed`) instead of
processing it again.

## Goal

1. Find the reuse decision in `apps/api/docgrain_api/routers/documents.py` / `repository.py` (grep for the
   content-hash reuse path). Reuse only versions whose latest job is `done` or `partial`; when the latest job is
   `failed`, create a new job for the same version (or a new version — follow the existing model; read it first)
   and enqueue it.
2. Unit test with the existing fake repository/fixtures: failed → re-upload → new queued job; done → re-upload →
   reused.

## Rules

Before you use a function or column, grep that it exists. Do not delete existing code; if you replace a function,
keep the old one marked unused with a comment. No network in tests.

## Acceptance criteria

- [ ] The two tests above pass; `.venv/Scripts/python -m pytest -q` green; ruff clean.
- [ ] Report (Turkish): the exact place you changed and why.
