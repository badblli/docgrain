# wp66-tailwind-shadcn — the web on Tailwind CSS and shadcn/ui, no hand-written CSS

- Özet: Web konsolunu düz CSS'ten Tailwind CSS v4 + shadcn/ui (Radix) + lucide ikonlarına taşı; marka kiti token'ları Tailwind teması olsun; elle yazılmış CSS dosyaları silinsin.
- Model: derin
- Engine: codex
- Skill: frontend-design
- Phase: D7
- Branch: `codex/wp66-tailwind-shadcn` (base: `origin/dev`; the lead commits the tooling setup first)
- Depends on: wp63 (merged)
- Role: implementer

## Decision (user, 2026-10-06)

"Düz CSS kullanmayalım." The console moves to the standard Next.js stack: Tailwind CSS v4, shadcn/ui
components (Radix primitives, `class-variance-authority`, `tailwind-merge`, `clsx`), `lucide-react` icons.

## Already set up by the lead (first commit on this branch)

Tailwind v4.3 + `@tailwindcss/postcss` (`postcss.config.mjs`), shadcn (style `radix-nova`, Radix, lucide)
via the official CLI: `components.json`, `lib/utils.ts` (`cn` from shadcn's verified `cn` package), and
components in `apps/web/components/ui/` (avatar, badge, button, card, dialog, dropdown-menu, input, label,
progress, scroll-area, select, separator, sheet, skeleton, table, tabs, textarea, tooltip). `@/*` maps to
`apps/web/*`. `app/globals.css` already starts with the shadcn theme block the CLI wrote; replace its colors
with the brand. The CLI's Geist font was removed: load Instrument Sans, Source Serif 4 and JetBrains Mono with
`next/font/google` (variables for `--font-sans`, `--font-serif`/doc, `--font-mono`) and drop the CSS
`@import url(fonts.googleapis…)`. Use these components; you cannot install packages.

## Tasks

1. Theme: map `docs/brand/tokens.css` into Tailwind v4 `@theme` (colors: ground, paper, sheet, ink, muted,
   line, accent, ok, warn, danger + soft/line variants; fonts: ui/doc/mono; radius; shadows) and the shadcn
   CSS variables (`--background`, `--foreground`, `--primary`, `--card`, `--border`, `--ring`, …) to the
   same brand values, light and dark (`prefers-color-scheme` and `.dark`). One stylesheet: `app/globals.css`
   with `@import "tailwindcss";`, the theme, and nothing else hand-written (a few `@layer base` rules for
   body/fonts are fine).
2. Rewrite every screen and component with Tailwind utilities + the shadcn components: sidebar (Sheet on
   mobile), company switcher (DropdownMenu or Select), metric tiles (Card), collection cards, review-state
   badges (Badge variants via cva: oneri / bekliyor / onay / red), question card grouped by document,
   Sorular list + progress (Progress) + filter (Select), Koleksiyonlar, Belgeler (table), empty states,
   developer mode, and the older canonical/review workspace views.
3. Delete `screens.css`, `canonical.css`, and the component `.css` files; `globals.css` shrinks to the theme.
   Icons: replace hand-drawn SVG icons with `lucide-react`.
4. Keep behaviour identical (API calls, revision pinning, 409 handling, answers by document, hydration-safe
   company picker); keep the approved look of `docs/brand/docgrain-brand.html`.

## Acceptance criteria

- [ ] No `.css` files under `apps/web/app` except `globals.css`; no `className` strings referring to removed
      classes; `grep -r "style={{" apps/web/app` only for truly dynamic values (e.g. a width percentage).
- [ ] `npx tsc --noEmit -p apps/web` clean; the lead runs `npm run build` and checks the screens on real data
      in light and dark at desktop and 390 px.
- [ ] Report in Turkish: component inventory (which shadcn component where), anything not migrated.

## Notes

- Use your `frontend-design` skill. Never install packages, never start servers or builds.
