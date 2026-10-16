# wp120-background-field-fill — Adding a field returns at once; filling runs as a job

- Özet: Kullanıcı yeni alan eklediğinde alan hemen eklensin ve yeni şema sürümü dönsün; alanın belgelerden doldurulması arka planda bir bilgi işi olarak çalışsın, ilerlemesi ekranda görünsün ve bitince yeni bir revizyon olarak yayınlansın.
- Model: derin
- Engine: codex
- Phase: D21
- Branch: `codex/wp120-background-field-fill` (base: `origin/dev`)
- Depends on: WP116 (merged, PR #109)
- Role: implementer
- Owner: Porygon (codex)

## Why

WP116 fills a user-added field from the pinned document contexts inside the HTTP request
(`RecordsRepository.user_change` → `field_filler` = `apps/api/docgrain_api/field_fill.py:fill_new_field` →
`packages/records/docgrain_records/targeted_fill.py:fill_field`), while it holds the workspace lock. With the
workspace model on this is one model call per document and can take minutes: the request times out, and every
answer, edit and job start of that workspace waits on the lock.

## Goal

`POST /v1/workspaces/{w}/collections/{c}/fields` publishes the schema revision with the new (empty) field and
returns at once. When the model is on, the same request (same workspace lock) creates a durable **field-fill
record job** and queues it on `docgrain:records`. The worker runs it with the existing record-job fencing,
heartbeat, deadlines and progress, and publishes one new revision (child of the field revision) through
`apply_review_rules` (decision 20 auto-accept; conflicts become questions). The web shows its progress and reloads
the collection when it is done.

## Design (lead decisions — follow them)

1. **Same table, new kind.** A field-fill job is a `record_jobs` row with `"kind": "field_fill"` (full jobs have no
   `kind` or `"records"`). The one-active-job-per-workspace index therefore fences it like a full job: answers,
   user edits and `record-jobs` starts get the existing 409 while it runs. Payload adds `collection`, `field`,
   `base_revision_id` (the field revision just published), `context_job_id` (the full record job whose
   `runtime/<sha256(job_id)>/schema` contexts are pinned — resolved in the API with the existing ancestor walk,
   no file reads of contexts there), `settings_version`, `model_enabled: true`, `publication_head` =
   `base_revision_id`, `sources: []`. Stages: `("fill", "publish")`, labels "Yeni alan belgelerden dolduruluyor" /
   "Yayın hazırlanıyor", `total_stages = 2`, own stage timeouts (fill 3600 s, publish 300 s). Keep `STAGES` of the
   full job unchanged; add a `FILL_STAGES` tuple and let the lifecycle helpers (`finish`, `expired`, the router
   read) use the job's own stages/`total_stages`.
2. **Starting it** lives in `apps/api/docgrain_api/records_jobs.py` (e.g. `start_field_fill(store, revision,
   collection, field)`), called from `user_change` through an injected callback (like `field_filler` today, so
   `records_repository.py` still does not import `records_jobs`). Called while `user_change` already holds the
   workspace lock and after `_publish(updated)` succeeded. No model call and no HTTP in the request. Outcomes:
   - model off → no job; note "Model kapalı; alanı elle doldurabilirsiniz." (as today);
   - model on but not ready / pinned contexts not found / identity field → no job; note
     "Alan eklendi; belgelerden doldurulamadı. Değerleri elle girebilirsiniz.";
   - queue push fails → `finish(..., "dispatch")`, same fallback note, request still 200;
   - job queued → note "Alan eklendi; değerler belgelerden aranıyor." and the response adds `"fill_job_id"`.
   The note is stored on the `add_field` user change as today.
3. **Worker.** `apps/worker/docgrain_worker/records_pipeline.py:process_job` dispatches on `job.get("kind")`:
   `field_fill` runs a new small runner (new module `apps/worker/docgrain_worker/field_fill_job.py` is fine) that
   reuses the same claim/heartbeat/terminal-error code path. The runner:
   - `fill`: guard (job still running, not expired, `resolve_workspace_model(workspace, settings_version)`, not
     fixtures), load and sha256-verify the pinned contexts of `context_job_id` exactly as `fill_new_field` does
     today, derive a child revision of `base_revision_id` (new `rev_` id, `parent_id` = base, same pattern as
     `user_changes.py`), run `targeted_fill.fill_field`, set the `add_field` change note of that field to the result
     note ("Belgelerde doğrulanabilen değerler eklendi; diğerleri boş kaldı." / "Doğrulanamayan belge önerileri
     eklenmedi."); record rejected counts in `metadata.rejected_fields` so `records_jobs.summary` shows them.
   - `publish`: `store.publish(child, check=…, complete=…, job_id=…)` like `Pipeline.publish`, where `check`
     re-runs the guard and requires the publication head to still be `base_revision_id` (else
     `publication_changed`); `complete` verifies the reads and calls `lifecycle.finish(..., revision_id=child.id)`.
     Do **not** apply the full job's `has_accepted` fence: a fill adds candidates under the review rules, it never
     overwrites a person's acceptance.
   - Model off at run time / settings changed → `guard` error, nothing published. Any failure leaves the field
     revision as head (field exists, empty).
   - Move the context-loading/ChatClient part of `field_fill.py` into a reusable function the worker calls; keep
     `fill_new_field` (marked `KULLANILMIYOR (karar 18, WP120)`) — do not delete it.
4. **Ancestor walk fix.** After a fill job publishes, its manifest carries the fill job's `record_job_id`; its
   runtime dir has no schema contexts. The ancestor walk that finds `context_job_id` must skip publications whose
   job is a `field_fill` job (look up the job kind via `records_jobs_repository.get`), so adding a second field
   after a fill still finds the full job's contexts.
5. **Router / read.** `GET record-jobs/latest|{id}` also returns `kind`, `collection`, `field` (keys, no source
   text). `records_jobs.summary` works for both kinds. The full job's `start()` is unchanged apart from the shared
   fence. The finish message for a fill job: "Yeni alan dolduruldu; onay bekleyenleri Sorular'dan kontrol edin".
6. **Web** (Tailwind + shadcn only, no new CSS, plain Turkish):
   - `record-job-progress.tsx`: `RecordJob` gets optional `kind`/`collection`/`field`; stage labels for `fill`;
     titles for a fill job ("Yeni alan dolduruluyor", "Yeni alan dolduruldu", "Yeni alan doldurulamadı; değerleri
     elle girebilirsiniz. Alan eklendi ve korunuyor.").
   - Koleksiyonlar (`information/information.tsx`, `collection-actions.tsx`): after "Alan ekle" returns
     `fill_job_id`, show the existing `RecordJobProgress` card in the collection view, poll until terminal (reuse
     `useRecordJob` or its fetch pattern; the existing `/record-jobs/latest` poll in `page.tsx` already sees the
     job), and on `done` reload schema + records so the new values appear. Edit buttons stay usable but a 409 while
     the fill runs must show "Yeni alan dolduruluyor; bitince tekrar deneyin."
   - Developer mode may show the job id; normal mode shows no codes.

## Scope

- In: `apps/api/docgrain_api/{records_repository.py,records_jobs.py,field_fill.py,routers/records.py,routers/record_jobs.py}`,
  `apps/worker/docgrain_worker/{records_pipeline.py,field_fill_job.py}`, `packages/records/docgrain_records/targeted_fill.py`
  (only if needed), `apps/web/app/components/{record-job-progress.tsx,information/*}`, `apps/web/app/page.tsx` (only
  if needed), tests under `tests/unit/`.
- Out: changing extraction/matching (`extractor.py`, `match*.py`, `merge.py`), the full record job's stages,
  database migrations (payload is JSONB; no schema change), Docker files.

## Rules

Do not delete code (mark replaced code `KULLANILMIYOR (karar 18, WP120)`; keep a copy of a replaced function next to
it or under `unused/wp120/`). No real model in tests (fake chat / fake transport). Never log exception text or
source text. Agents never run Git.

## Acceptance criteria

- [ ] Test: add field with model on → response has new `workspace_schema_version`, `fill_job_id`, and returns
      without calling the model (fake filler/chat asserts zero calls during the request); a `field_fill` job row is
      queued; the fence makes answers / user edits / `record-jobs` start 409 while it is active.
- [ ] Test: running the fill job with a fake chat → status `done`, a new head revision whose parent is the field
      revision, verified values published through `apply_review_rules`, unverifiable quotes rejected and counted in
      the job summary; progress stages `fill` → `publish`, `completed_stages == total_stages == 2`.
- [ ] Test: job failure (chat raises / context sha mismatch / head changed) → status `failed` with a fixed code,
      head stays the field revision, field still in the schema, no exception text persisted.
- [ ] Test: model off → no job, note "Model kapalı; alanı elle doldurabilirsiniz.", schema version +1.
- [ ] Test: second field added after a successful fill still finds the full job's contexts (ancestor walk skips
      fill jobs).
- [ ] Existing WP116 / U1 pipeline / structure-first tests still pass (update `test_failed_fill_still_adds_the_field_with_a_note`
      to the new flow without weakening it).
- [ ] `.venv/Scripts/python -m pytest -q` green, `.venv/Scripts/ruff check .` clean, `npx tsc --noEmit` 0 in
      `apps/web`, web tests green (`npm test` in `apps/web` if present).
- [ ] Report (Turkish): what changed, files, test counts, and the lead's live check steps.

## Notes

- Lock: `RecordsRepository._workspace_lock` is the OS lock shared by API, worker and offline publishers;
  `process_job` takes it to claim (`queued → running`), `store.publish` takes it to commit. Do not hold it during the
  model calls.
- `_publication_ready` already hides a publication until its job row is `done` with the same `revision_id`.
- Test helpers for jobs: see `tests/unit/test_u1_pipeline.py` and `tests/unit/test_structure_first.py` (fake job
  repository / fake queue patterns); WP116 tests in `tests/unit/test_user_schema_and_records.py`.
