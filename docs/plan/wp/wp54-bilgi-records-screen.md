# wp54-bilgi-records-screen — "Bilgi" screen shows the published records

- Özet: Web'deki "Bilgi" ekranı, yayınlanan kayıtları (odalar, restoranlar…) kart olarak göstersin; her alanın durumu (öneri / onaylı) ve kaynağı tek tıkla görülsün.
- Model: derin
- Engine: agy
- Phase: D7
- Branch: `codex/wp54-bilgi-records-screen` (base: `origin/dev`)
- Depends on: wp43 (records read API, merged)
- Role: implementer

## Goal

Today the "Bilgi" screen in `apps/web/app/page.tsx` is an empty placeholder. A non-technical user should
open it and see the workspace's collections as simple cards, with each record's fields, a small badge
for the review state, and "Kaynakta göster" for the evidence.

## Scope

- In: `apps/web/app/**` (new components under `apps/web/app/components/information/` preferred).
  If the web cannot discover which revision to show, add one small read-only endpoint
  `GET /v1/workspaces/{workspace_id}/revisions` in `apps/api/docgrain_api/routers/records.py` +
  `records_repository.py` (list published revision ids, newest first) with unit tests.
- Out: editing records, approving values, any change to extraction/merge/export, styling outside the
  Bilgi screen.

## Tasks

1. Read `apps/api/docgrain_api/routers/records.py`, `records_repository.py`, `docs/examples/records-read.md`
   to learn the API (`/v1/workspaces/{ws}/revisions/{rev}/collections[/{collection}[/records/{id}]]`,
   `mode=preview|approved`, `lang=`, ETag).
2. Bilgi screen: collection list (localized label, record count) → collection cards → record detail.
   Show the primary value; other languages behind a small "Diller" toggle. Badge per field:
   `proposed` → "Öneri", `needs_review` → "İnceleme bekliyor", `accepted` → "Onaylandı".
   Evidence opens a short source reference (document, page/cell) — no raw JSON in the default view.
3. A "Önizleme / Onaylı" switch (default Önizleme). Empty states in plain Turkish (no data yet,
   API unreachable).
4. Developer details (raw JSON, ids) only behind the existing "Geliştirici modu".
5. Mobile 390 px without horizontal overflow.

## Acceptance criteria

- [ ] `cd apps/web && npm run build` passes (TypeScript included).
- [ ] If the API changed: `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass.
- [ ] No technical words (JSON, revision, evidence, id) in the default view.
- [ ] Report: what each state looks like in words, which API calls the screen makes, and what you
      could not verify (you cannot run the browser).

## Notes

- Real data: the lead publishes a merged revision locally after merge; you work against the API
  contract and fixtures (`tests/unit/test_records_api.py` shows example payloads).
- You run inside a sandbox: no Git writes, no installs, no network. `node_modules` already exists.
