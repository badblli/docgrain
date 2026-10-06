# wp63-apply-brand — the web console wears the Docgrain brand

- Özet: Smeargle'ın kullanıcı tarafından onaylanan marka kitini (logo, renk/yazı token'ları, bileşen dili, belgeye göre gruplu soru kartı) web konsoluna uygula.
- Model: derin
- Engine: codex
- Skill: frontend-design
- Phase: D7
- Branch: `codex/wp63-apply-brand` (base: `origin/dev`)
- Depends on: wp62 (brand kit, approved by the user 2026-10-06), wp60, wp61 (merged)
- Role: implementer

## Source of truth

- `docs/brand/BRAND.md` (rules and implementation notes, Turkish) — follow it.
- `docs/brand/tokens.css` (light + dark tokens) — the only colors, type, radius, spacing, shadow, motion.
- `docs/brand/docgrain-brand.html` — the approved look of components and the Özet and Sorular screens
  (published for the user as "Docgrain Marka Kiti"). Match it closely.
- `apps/web/public/brand/` — `logo.svg`, `logo-mark.svg`, `logo-mono.svg`, `favicon.svg`.

## Tasks

1. Tokens: bring `tokens.css` into the app (one source; remove duplicated/legacy literals, e.g. the old
   `#37352f` neutrals and `.brandMark` box in `globals.css`), dark theme via `prefers-color-scheme`.
2. Logo in the sidebar (full logo), favicon + app icon via Next metadata, page title "Docgrain".
3. Components per the kit: sidebar (company switcher with avatar initial, nav with amber question badge),
   metric tiles (Onaylı with a meter), collection cards (status bar: ok / warn / proposed), review-state
   pills (Öneri / İnceleme bekliyor / Onaylandı / Reddedildi with shape + color), buttons, empty states,
   source quote with the highlighted value (`mark`) in the serif, locator in mono.
4. Question card grouped **by source document**: one group per document ("<dosya> diyor ki", that
   document's value(s), its quotes, its locator) with a "Bu belge güncel" button per group.
   API addition (small, in `packages/records/docgrain_records/review.py` + router, with tests): answer body
   `{"document_id": "<id>"}` accepts every option whose evidence comes from that document (one value →
   that value; several → a list value) and rejects the others; same revision/409 rules as other answers;
   expose `document_id` on each option in `GET …/questions` so the UI can group. "Hepsi doğru" only when
   `allow_all` is true. Footer: "İkisi de yanlış, düzelt" (2 groups) / "Hiçbiri doğru değil, düzelt"
   (3+), "Sonra sor", "n / N". After an answer: inline "Kaydedildi" note (no "Geri al": the API has no
   undo yet).
5. Sorular screen per the kit: progress line, collection filter, question list on the left (state dots:
   open, later, done), the card on the right; stacks on narrow screens.
6. Responsive: below ~780px the sidebar becomes a top bar with four nav items; 390px without
   horizontal overflow.

## Acceptance criteria

- [ ] `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass (API addition).
- [ ] `npx tsc --noEmit -p apps/web` clean (the lead runs `npm run build` and checks the screens on real data).
- [ ] No hard-coded colors outside the token file; dark theme readable everywhere.
- [ ] Report in Turkish: what changed per screen, anything in the kit you could not follow and why.

## Notes

- Use your `frontend-design` skill; the direction is approved, so refine within the kit, don't reinvent.
- `apps/web/node_modules` is linked into your worktree; never install, build or start servers.
