# wp125-update-after-approval — Update records after a person approved them, without losing their work

- Özet: Bir kişi değerleri onayladıktan sonra da "Bilgileri çıkar" yeniden çalışabilsin; değişmeyen belgeler yeniden işlenmesin, kişinin onayları, düzeltmeleri ve cevapları korunsun, yalnızca belgesi değişen değerler yeniden değerlendirilsin ve onaylı bir değer değiştiyse sessizce ezilmek yerine soru olarak sorulsun.
- Model: derin
- Engine: codex
- Phase: D3
- Branch: `codex/wp125-update-after-approval` (base: `origin/dev`)
- Depends on: none (WP124 adds real new versions; tests here simulate a changed latest version)
- Role: implementer
- Owner: Porygon (codex)

## Why (lead reading, 2026-10-30)

- `apps/api/docgrain_api/records_jobs.py` `start()` raises `JobConflict("publication_changed")` when
  `has_accepted(store, workspace)` — once a person accepted anything on the head revision, **no records job can run
  again**. So after the first review a company can never add or update a document. This is the opposite of D3.
- `records_pipeline.py` `publication_unchanged()` repeats the same guard during the run.
- Every job reprocesses every pinned document (`structure`, `discover`, `extract` for all documents), including the
  model fallback for documents whose content did not change.
- Earlier "same list?" answers are already inherited from the head (`_remembered`, WP119); field-level human
  decisions are not.

## Read first

`records_jobs.py` (`source_snapshot`, `head`, `has_accepted`, `start`), `apps/worker/docgrain_worker/records_pipeline.py`
(stages, `_load_documents`, `_remembered`, `structure`, `extract`, `merge`, `publish`), `packages/records/docgrain_records/`
`merge.py`, `merge_models.py` (`SourcePin`, `VersionedEvidence`, candidates, `review_state`), `auto_accept.py`
(karar 20), `review.py`, `user_changes.py` (WP116 `user_edit` evidence), `verify.py`, `field_fill_job.py` (WP120),
ROADMAP decisions 20 and 21.

## Goal

1. **Allow the job after approval.** Replace the `has_accepted` block with an "update" run: it starts from the
   published head and carries human work forward. Keep the guard against a concurrent publication (head moved
   while running) — that is still `publication_changed`.
2. **Reuse unchanged documents.** A pinned document whose `content_sha256` and `knowledge_revision_id` equal the
   head revision's source pin is not re-extracted: its structure/model results come from the previous run (store
   what is needed per document so this is possible; no model call for it). Record in job metadata how many
   documents were reused vs processed and how many model calls were saved.
3. **Carry human decisions forward, per field candidate**, after merge and before publish:
   - person accepted / rejected / corrected a value, its evidence still verifies in the new pinned source
     (same quote found in that document's current context) → keep the decision exactly as it was;
   - evidence document unchanged → keep (no re-verification needed);
   - evidence document changed and the quote is gone, and the new run proposes a different value → do **not**
     overwrite: the field becomes a question "Belge değişti: önceki onaylı değer X, belgedeki yeni değer Y" with both
     sources, previous value still published until answered;
   - evidence document removed from the workspace → value marked as having no current source (question), never
     silently dropped;
   - `user_edit` values (WP116) and user-added fields/collections/records always survive;
   - answered duplicate / conflict / "same list?" questions stay answered when their inputs are unchanged.
   Karar 20 still applies to new, non-conflicting values.
4. **Old revision stays queryable** (it already is by revision id; add a test).
5. Report counts in job metadata: kept decisions, re-asked decisions, new values, removed values.

## Scope

- In: `records_jobs.py`, `records_pipeline.py`, `packages/records/` (new module allowed, e.g. `carry_forward.py`),
  their tests.
- Out: document upload/versions/diff (WP124 — do not touch `routers/documents.py`, `routers/versions.py`,
  `packages/domain/.../canonical/`), web UI, webhooks.

## Rules

Never delete replaced code: the old guard stays as a function marked `KULLANILMIYOR (karar 18, WP125)`. No real
model in tests (fake loaders/clients as in existing pipeline tests). Synthetic data only. No network, Git or builds.

## Acceptance criteria

- [ ] Pipeline tests with a workspace of 3 synthetic documents, a published head with person-accepted values:
  - nothing changed → job runs, **0** documents re-extracted, 0 model calls, every human decision identical;
  - one document's latest version changes one value that a person had accepted → that field becomes one question
    with old and new values; all other accepted values unchanged; previous value still published;
  - one document changes a value nobody reviewed → new value auto-accepted by the rule (karar 20), no question;
  - a `user_edit` value and a user-added field survive an update run;
  - a document removed → its values become "no current source" questions;
  - head moved during the run → `publication_changed` as before.
- [ ] `.venv/Scripts/python -m pytest -q` green, `.venv/Scripts/python -m ruff check .` clean.
- [ ] Report in Turkish: design, what is stored per document for reuse, the metadata counts, and the lead's live
      steps (approve a value on a demo workspace, change one document, re-run "Bilgileri çıkar").

## Notes

Parallel with WP124 (Charizard). If you need "which units changed" inside a document, read WP124's diff module
docstring once it exists; until then compare evidence quotes against the new context, which is enough for the
acceptance above.
