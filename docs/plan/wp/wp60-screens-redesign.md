# wp60-screens-redesign — Özet, Sorular, Koleksiyonlar, Belgeler

- Özet: Web konsolunu yeniden tasarla: açılışta şirket özeti ve kullanıcıdan cevap bekleyen çelişki soruları; ardından Koleksiyonlar ve Belgeler. Kullanıcı (onaylandı, 2026-10-06) bu yönü seçti.
- Model: derin
- Engine: codex
- Skill: frontend-design (user decision 2026-10-06: design work runs on Codex or Claude with the frontend-design skill)
- Phase: D7
- Branch: `codex/wp60-screens-redesign` (base: `origin/dev`)
- Depends on: wp59 contract (built in parallel; this WP codes against the contract below)
- Role: implementer

## How to work

Use your `frontend-design` skill for this work package: commit to the approved direction below, define the
visual system first (type scale, palette tokens, spacing, surfaces, motion), then build. Another agent
left two partial files (`apps/web/app/components/question-card.tsx`, `summary.tsx`); review them and keep,
rewrite or delete as you see fit.

## Design (approved by the user)

Left sidebar: product name, "Şirket" picker (from wp56), then four items: **Özet** (default), **Sorular**
(with a small amber count badge), **Koleksiyonlar**, **Belgeler**. (User, 2026-10-06: the lists are called "Koleksiyonlar", never "Bilgiler".) "Geliştirici modu" stays at the bottom.

- **Özet**: company name, "N belgeden derlendi · son güncelleme …"; four metric tiles: Kayıt, Kaynaksız
  bilgi (green when 0), Çelişki (amber), Onaylı (%). Below: "Sizden bir cevap bekliyor" with the first
  open question card, then the collection cards (icon, Turkish label, "X kayıt · Y çelişki" or
  "tamamı onaylı").
- **Question card** (used on Özet and Sorular): small amber line "Kaynaklar farklı söylüyor ·
  <liste>", the question in plain Turkish ("<kayıt adı> için <alan etiketi> hangisi?"), options side by side
  (stack on mobile): big value, a short quote in quotes + document name (and page), button "Bu doğru".
  Under the options: "İkisi de yanlış, düzelt" (inline input → submit), "Sonra sor", and "1 / N".
  After an answer: short confirmation ("Kaydedildi") and the next question slides in.
- **Sorular**: the question card one at a time, a progress line, filter by list; empty state
  "Bütün sorular cevaplandı" with a link to Koleksiyonlar.
- **Koleksiyonlar**: current wp55 screen, restyled to the same cards; a record shows a small amber dot on fields
  with an open question that opens that question.
- **Belgeler**: current list, restyled: status as plain words ("Hazır", "Kontrol edilmeli"), upload as a
  quiet secondary action.
- Visual language: flat white surfaces, 0.5–1px hairline borders, 8px radius controls / 12px cards, one
  accent color for primary actions, amber only for conflicts, green only for "0 kaynaksız"/approved.
  Tabler-style outline icons are fine if already available; otherwise inline SVG. Generous whitespace,
  Turkish sentence case, no technical words in the default view. Mobile 390 px without horizontal overflow.

## API contract (from wp59 — use exactly; show a friendly empty/error state when an endpoint is missing)

- `GET /v1/workspaces/{ws}/summary` → `{workspace_id, revision_id, documents, records, unsupported_fields,
  conflicts, needs_review, accepted_ratio, updated_at, collections: [{key, label, records, conflicts, needs_review}]}`
- `GET /v1/workspaces/{ws}/questions?limit=20&offset=0` → `{total, items: [{id, kind, collection,
  collection_label, record_id, record_title, field, field_label, lang, options: [{candidate_id, value,
  display, quote, document_name, locator}]}]}`
- `POST /v1/workspaces/{ws}/questions/{id}/answer` body `{candidate_id}` | `{value, note}` | `{skip: true}`
  → `{revision_id, remaining}`; 409 means "Bu soru başka biri tarafından cevaplandı" → reload.

## Scope

- In: `apps/web/app/**` only (split `page.tsx` into components under `apps/web/app/components/`).
- Out: API changes (wp59), auth.

## Acceptance criteria

- [ ] `npx tsc --noEmit -p apps/web` clean (the lead runs `npm run build` and checks the screens).
- [ ] Report in Turkish: each screen's states (loading, empty, error, normal) in words.

## Notes

- `apps/web/node_modules` is linked into your worktree. Never run installs, builds, servers or anything
  that needs to leave the sandbox; run checks in the foreground.
