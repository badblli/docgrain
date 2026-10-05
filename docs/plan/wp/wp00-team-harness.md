# wp00-team-harness — Green CI and team harness

- Özet: dev CI'ını kıran 36 Ruff hatasını davranış değiştirmeden düzelt; ekip harness dosyalarını ekle.
- Phase: D0
- Branch: `codex/wp00-team-harness` (base: `origin/dev`, already checked out in the main checkout)
- Depends on: none
- Role: implementer + git (commit only; the lead approves push/PR separately)

## Goal

`dev` CI is red because `ruff check apps packages tests benchmarks docs/examples` reports 36
errors. Make Ruff pass without changing behavior, and commit the team harness files the lead
already wrote.

## Scope

- In: Ruff findings in `apps/`, `packages/`, `tests/`, `benchmarks/`, `docs/examples/`.
  Uncommitted harness files: `AGENTS.md`, `CLAUDE.md`, `docs/plan/**`, `scripts/team/**`,
  `.gitignore` change.
- Out: any behavior change, dependency change, Ruff config change, new rules or `# noqa` added
  just to silence a real finding.

## Tasks

1. Run Ruff and fix all findings. Auto-fixes (`I001`, `RUF022`) are fine.
2. `B023` (function uses loop variable): check each case. If the closure is called after the loop
   variable changes, it is a real bug — fix it by binding the value, and add a regression test if
   behavior was actually wrong. If it is called immediately inside the iteration, bind anyway
   (default argument) and say so in the report.
3. `TRY004`, `C408`, `BLE001`, `PLC0206`: fix in place. For `BLE001`, keep the broad catch only if
   it is a deliberate boundary; then narrow it or document why with a targeted `noqa` and reason.
4. Do not edit the lead's harness files except to fix obvious typos; just include them.
5. Commit in two commits: `chore(team): add team harness and roadmap mirror` (harness files) and
   `fix(lint): satisfy ruff rules` (code).

## Acceptance criteria

- [ ] `ruff check apps packages tests benchmarks docs/examples` → 0 errors.
- [ ] `python -m pytest -q` → no new failures (baseline: 384 passed, 89 skipped).
- [ ] Each `B023` case is listed in the report as "real bug" or "safe", with one-line reason.
- [ ] No `pyproject`/Ruff configuration changes.

## Notes

The host venv is `.venv` in the repo root (`.venv/Scripts/python -m pytest -q`).
