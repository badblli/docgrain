# wp109-web-default-workspace — Open the console on a company that has documents

- Özet: Web konsolu açılışta boş "Yerel" çalışma alanını değil, belgesi olan ilk şirketi (ya da kullanıcının son seçtiği şirketi) göstersin.
- Model: standart
- Engine: agy
- Skill: frontend-design
- Phase: U1
- Branch: `codex/wp109-web-default-workspace` (base: `origin/dev`)
- Depends on: none
- Role: implementer
- Owner: Alakazam (agy)

## Why (lead, 2026-10-09)

The console opens on `NEXT_PUBLIC_WORKSPACE_ID` (`ws_local`, 0 documents) and shows "hazır değil" cards, while 19
real companies exist (`GET /v1/workspaces` returns `id`, `name`, `documents`).

## Goal

1. In `apps/web/app/page.tsx` (and the sidebar company picker), choose the initial workspace in this order: the
   last one the user picked (stored in `localStorage`, wrapped in try/catch), else the first workspace with
   `documents > 0` from `GET /v1/workspaces`, else the env default.
2. Show the workspace `name` (not the id) everywhere the picker shows it.
3. No other behaviour change. Tailwind + shadcn only, no new CSS files.

## Rules

Read `apps/web/app/page.tsx` and `apps/web/app/components/sidebar.tsx` first; grep before using any helper. Do not
delete existing code. No new dependencies.

## Acceptance criteria

- [ ] `node apps/web/node_modules/typescript/bin/tsc --noEmit -p apps/web` exits 0; `node --test tests/web/test_u1_upload.mjs`
      and `node --test apps/web/app/components/workspace-review.test.cjs` stay green.
- [ ] Report (Turkish) with the files changed.
