# wp62-brand-system — Docgrain as a product: logo, colors, type, dashboard

- Özet: Docgrain'i ürünleştir: logo, renk ve yazı sistemi, bileşen dili ve Özet/Sorular dashboard tasarımı; Notion/Apple çizgisinde sade ama etkili. Mevcut ekran renkleri (wp60) beğenildi, temel alınacak.
- Model: claude (Smeargle, design agent)
- Engine: claude
- Skill: frontend-design + artifact design craft
- Phase: D7
- Depends on: wp60 (merged)
- Role: designer (writes design assets and a brand board; Codex implements in apps/web afterwards)

## Brief (user, 2026-10-06)

"Projeyi ürünleştirelim: logo, renkler, dashboard tasarımı. Biraz önceki renkler iyiydi; Notion/Apple
tasarım çizgisinde, sade ama efektif."

Docgrain turns a company's documents into normalized, source-linked collections (records with evidence)
that AI and apps can trust. Users are non-technical company staff who review facts and answer conflict
questions ("Kaynaklar farklı söylüyor"). Product promises: every fact has a source; conflicts are asked,
never guessed; versions are kept.

## Baseline to keep (apps/web/app/screens.css)

ground #fafbf9 · paper #fff · sheet #f5f7f6 · ink #223333 · muted #647573 · line #dce3e0 ·
accent #245d65 (deep teal ink) · accent-soft #eaf2f2 · ok #327251 / #eff6f1 · warn #956316 / #fff5df;
radius 8 / 12; Instrument Sans (UI), Source Serif 4 (document/quotes), JetBrains Mono (data).

## Deliverables

1. `apps/web/public/brand/`: `logo-mark.svg` (works at 16 px), `logo.svg` (mark + wordmark),
   `favicon.svg`, `logo-mono.svg` (single color). Concept from the subject: grains/pieces of a document,
   source-linked; no generic AI sparkle, no gradient.
2. `docs/brand/tokens.css`: the full token set, light and dark (dark designed, not inverted): neutrals with
   a slight teal bias, accent scale, semantic ok/warn/danger, surfaces, borders, radius, spacing, type
   scale, shadows (subtle), motion.
3. `docs/brand/BRAND.md` (Turkish, short): logo usage, palette roles, type roles, voice (sentence case,
   plain Turkish), component rules (cards, pills for review state, question card, metric tile, sidebar),
   do/don't — written for the Codex implementer.
4. `docs/brand/docgrain-brand.html`: a brand board page (the lead publishes it as an Artifact): logo
   variants, palette with roles, type specimens, components, and a high-fidelity **Özet dashboard** and
   **Soru kartı** in light and dark, using real-looking hotel content (no real company names).

## Rules

- Follow the artifact page contract the lead gives you for the HTML (title, tokens on :root with dark blocks,
  Google Fonts only, no external images, phone width, no horizontal scroll).
- Keep it calm: one accent, semantic colors only for state, hairline borders, generous whitespace,
  Notion/Apple restraint. One distinctive detail from the subject (e.g. evidence/quote styling).
- No code changes outside `apps/web/public/brand/` and `docs/brand/`.
