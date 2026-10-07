# wp96-wide-layout — Use the full width in the web console

- Özet: Ekranların içeriği ortada dar bir sütunda duruyor; içerik geniş ekranı kullansın, okunabilir metinler okunur genişlikte kalsın, menüde seçili ekran doğru görünsün.
- Model: derin
- Engine: claude
- Skill: frontend-design
- Phase: U1
- Branch: `claude/wp96-wide-layout` (base: `origin/dev`)
- Depends on: none (WP93 merged)
- Role: implementer
- Owner: Smeargle (claude)

## Why (user, 2026-10-07)

"Sayfanın içeriği geniş değil de kompakt ortalanmış duruyor; wide kullansak daha fazla alan açılırdı."

## Goal

Every console screen (Özet, Sorular, Koleksiyonlar, Belgeler, Dene, Ayarlar, Geliştirici modu screens) fills
the main area next to the sidebar on wide screens instead of a centered 1200 px column. Grids gain columns
as width grows. Prose (descriptions, answers, form help) keeps a readable measure (about 60–80ch); forms
such as Ayarlar may stay narrower but left-aligned with the page header, not floating in the middle.

## Tasks

1. Replace the centered `mx-auto max-w-[1200px]` shells (`apps/web/app/components/console-ui.tsx` page
   shell and header, `documents.tsx`, and any other screen container) with one shared full-width shell with
   consistent side padding (16 px phone, 24 px tablet, 40 px desktop).
2. Let card grids (collections, summary tiles, questions) add columns on wide screens (e.g. 2 → 3 → 4).
3. Ayarlar (`components/settings/workspace-settings.tsx`) and Dene (`components/try/try-view.tsx`):
   left-align with the header; Dene's answer and sources may use a two-column layout on wide screens.
4. Bug: after choosing Ayarlar (or Dene) in the sidebar, "Özet" stays highlighted for a moment — the active
   item must follow the current screen immediately.
5. Check 390 px, 1280 px and 1920 px in light and dark: no horizontal scroll, no overflow.

## Rules

Tailwind CSS v4 + shadcn/ui only. No new `.css` files, no new inline style objects, no new dependencies.
Keep behavior and API calls unchanged. Do not edit backend code.

## Acceptance criteria

- [ ] At 1920 px the content uses the main area width (minus padding); no screen has a centered fixed column.
- [ ] Prose stays readable; 390 px has no horizontal scroll.
- [ ] The sidebar highlight follows the screen immediately.
- [ ] `node node_modules/typescript/bin/tsc --noEmit -p apps/web` 0; `node --test tests/web/test_u1_upload.mjs`
      and `node --test apps/web/app/components/workspace-review.test.cjs` green; `next build` ok.
- [ ] Before/after screenshots at 1920 px and 390 px.
