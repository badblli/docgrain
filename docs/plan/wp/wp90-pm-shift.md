# wp90-pm-shift — Project manager shift while the lead is away

- Özet: Lead dönene kadar ekibi yönet: çalışan ajanları izle, raporlarını kabul ölçütlerine göre incele, geri bildirim ver, sonraki iş paketlerinin taslağını yaz, devir notu bırak.
- Model: standart
- Phase: D4
- Branch: none (work in the main checkout; do not commit)
- Depends on: none
- Role: project manager (Slowking)

## Context
Goal: every document type → normalized → versionable meaningful pieces (typed records) feeding
both AI context and JSON for web/mobile (read `docs/plan/ROADMAP.md`, `AGENTS.md`). Test hotel:
Prime Beach (`C:/Users/root/Documents/work/others/prime beach/`). EN-first: English source wins
as primary value, other languages go to `i18n`. Never touch `sonDB/` or `yeni db/` there.

Running now: **wp41-record-extractor** (Charizard) and **wp71-simple-ui** (Jigglypuff).
State: `.lead/board.json`, `.lead/chat/<wp>.jsonl`, `.lead/runs/<wp>/<ts>/` (status, report.md).

## Your loop (about 2.5 hours; poll every 2–3 minutes with a shell sleep)
1. When a run's `status` becomes `done`: read its `report.md` and the diff in its worktree
   (`git -C ../docgrain-wt/<wp> diff` + untracked files). Re-run the WP's acceptance commands with
   `C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python` (and `npm run build` for web).
2. Decide: if criteria are met → `python scripts/team/board.py step <wp> approved "<why>"`.
   If not → `python scripts/team/board.py step <wp> changes_requested "<what>"` and send the agent
   precise feedback with `scripts/team/tell.sh <wp> "<feedback>"` (max 2 rounds per WP).
   If tell.sh cannot start in your sandbox, write the feedback into `.lead/pm-handoff.md` instead.
3. Write the next WP specs as files (do not run them): `docs/plan/wp/wp42-record-merge.md`
   (cross-document/cross-language merge, visible conflicts, stable record ids, field-level version
   diff — owner Alakazam/bora, Model: derin), `docs/plan/wp/wp43-records-json-api.md`
   (rooms.json/outlets.json… export + read API for web/mobile + compact AI context from records —
   owner Porygon/cem, Model: standart), `docs/plan/wp/wp45-primebeach-golden.md` (held-out field
   golden + questions for Prime Beach — owner Bulbasaur/ece, Model: derin). Use
   `docs/plan/wp/TEMPLATE.md`; Turkish `- Özet:` line; keep each under 60 lines.
4. Post short Turkish progress notes: `python scripts/team/board.py say wp90-pm-shift pm "<note>"`.
5. Keep `.lead/notion-draft.md` updated with Notion-ready progress notes (tasks, status, findings)
   for the scribe to publish later.

## Hard rules
- Never commit, push, merge or open PRs. Never edit agents' worktrees yourself — feedback only.
- Do not start new agent runs (run-wp.sh); the lead launches the next WPs.
- No external model calls.

## Finish
Write `.lead/pm-handoff.md`: per WP status, what you approved/rejected and why, open questions for
the lead, next WP specs written. Then end with the AGENTS.md report format.
