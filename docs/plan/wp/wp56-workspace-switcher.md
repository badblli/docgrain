# wp56-workspace-switcher — pick the company in the web console

- Özet: Web konsolunda sol menüden şirket (çalışma alanı) seçilebilsin; Belgeler ve Bilgi ekranları seçilen şirketin verisini göstersin.
- Model: standart
- Engine: agy
- Phase: D7
- Branch: `codex/wp56-workspace-switcher` (base: `origin/dev`)
- Depends on: wp50 (workspace-scoped bundles, merged), wp55 (merged)
- Role: implementer

## Goal

Companies are now ingested into their own workspaces (`ws_primebeach`, `ws_dobedan`, `ws_susesi`,
`ws_nirvana`, plus the old `ws_local`). The web console is pinned to one workspace via
`NEXT_PUBLIC_WORKSPACE_ID`. A user must switch company from the sidebar.

## Scope

- In: `apps/web/app/**`; one small read-only API endpoint `GET /v1/workspaces` (distinct workspace ids
  that have documents, with document counts) in `apps/api/docgrain_api` + unit tests, only if no such
  endpoint exists (check `routers/documents.py` and the repository first).
- Out: auth, creating/deleting workspaces, any processing change.

## Tasks

1. API (if missing): `GET /v1/workspaces` → `[{ "id": "ws_primebeach", "documents": 7 }, …]`, newest
   activity first; works in fixture mode and the Postgres repository.
2. Web: a workspace picker at the top of the sidebar ("Şirket"), showing a friendly name
   (`ws_primebeach` → "Primebeach"; keep a small override map for nicer names) and the document count.
   The choice is remembered in `localStorage` and defaults to `NEXT_PUBLIC_WORKSPACE_ID`.
3. Belgeler list (`/v1/documents?workspace_id=`) and Bilgi screen use the selected workspace;
   switching reloads both and shows the empty states when a workspace has no data yet.
4. No technical words in the default view; mobile 390 px without overflow.

## Acceptance criteria

- [ ] `npx tsc --noEmit -p apps/web` clean (the lead runs `npm run build`).
- [ ] If the API changed: `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass.
- [ ] Report in Turkish: what the picker looks like, which calls change with the workspace, what you could not verify.

## Notes

- `apps/web/node_modules` is linked into your worktree; never try to install or link packages.
- Do not run commands that need to leave the sandbox (builds, servers, network); the lead runs them.
