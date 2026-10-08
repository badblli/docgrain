# wp101-u1-smoke-rewrite — Rewrite the U1 smoke test on the real functions and contracts

- Özet: U1 smoke testini gerçek yükleme fonksiyonu ve gerçek API sözleşmeleriyle yeniden yaz; liderin canlı yürüyüşünde geçen adımları otomatik ve tekrarlanabilir kıl.
- Model: derin
- Engine: codex
- Phase: U1
- Branch: `codex/wp101-u1-smoke-rewrite` (base: `origin/dev`)
- Depends on: WP91, WP92, WP94 (merged)
- Role: implementer
- Owner: Bulbasaur (codex)

## Why

The WP95 script (`../docgrain-wt/wp95-u1-smoke/docs/examples/u1_smoke.py`) used invented endpoints
(`/health`), uploaded the bytes "fake content" instead of the fixtures, waited for a status that does not
exist and exited before printing its report. Keep its fixtures (`tests/fixtures/u1-company/`: two TXT files,
`golden.json`, README) — they are good. The lead walked the real path successfully on 2026-10-08 with
`.lead/u1_walk.py` (private, reproduced below) on the live stack:

1. `POST /v1/workspaces {"name"}` → 201 `{id}`.
2. Model off: `POST /v1/workspaces/{ws}/ai/ask` and `POST /v1/workspaces/{ws}/record-jobs {"request_id"}` → 409.
3. Upload with `docgrain_ingest.cli.ingest_folder(folder, ws, client, report_path=..., timeout=...)` → files `done`.
4. `PUT /v1/workspaces/{ws}/model {"enabled": true, "base_url", "model", "credential_id"}` → 200,
   `credential_ready: true` (profiles from `GET /v1/workspaces/{ws}/model/profiles`).
5. `POST /v1/workspaces/{ws}/record-jobs` → 202 `{job_id}`; poll `GET …/record-jobs/{job_id}` until `status` in
   `done|failed|needs_review` (stages discover → … → publish, about 2 minutes with a real model).
6. `GET /v1/workspaces/{ws}/summary` → records, `unsupported_fields` (must be 0), `conflicts` (the planted
   32/36 m² conflict must be 1), `needs_review`.
7. `GET /v1/workspaces/{ws}/questions` → items with `kind`, `field`, `options[{candidate_id, value, document_name,
   quote, locator}]`; answer each with `POST …/questions/{id}/answer {"candidate_id"}` choosing the golden value
   (32 for the conflict) → 200 with a new `revision_id` and `remaining`.
8. Summary → `accepted_ratio` 1.0, conflicts 0.
9. `POST …/ai/ask` "Bahçe Odası kaç metrekare ve kaç kişilik?" → answer contains 32 and 2, sources from
   `odalar.txt`; "Otelin helikopter pisti var mı?" → `abstained: true`, answer "Bilmiyorum.", no sources.

## Goal

1. Replace `docs/examples/u1_smoke.py` (move it into the repo from the WP95 worktree, with the fixtures, the
   unit and live tests) with a script that follows exactly the steps above, compares values against
   `golden.json`, prints a pass/fail line per step with durations, writes `report.json`/`report.md`, and exits
   non-zero after printing when any step fails or is blocked.
2. A fake mode for unit tests that uses `httpx.MockTransport` implementing the same contracts (no network).
3. Live mode needs `--api`, `--credential-id`, `--base-url`, `--model`; never reads or prints keys.
4. `tests/integration/test_u1_smoke_live.py` runs the live mode only with an explicit opt-in env variable.

## Rules

Grep every endpoint in `apps/api/docgrain_api/routers/` before using it. No invented fields. No network in
unit tests.

## Acceptance criteria

- [ ] Fake mode: pass scenario passes; wrong value (36 accepted), missing sources, unsupported field > 0,
      job `failed`, and an invented source on the unknown question each make the run fail.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean.
- [ ] Report (Turkish) with the exact live command for the lead.
