# wp71-simple-ui — Understandable Docgrain web UI

- Özet: Web arayüzünü teknik olmayan kullanıcı için sadeleştir: Belgeler / Belge / Bilgi ekranları, teknik terimler sadece Geliştirici modunda.
- Model: standart
- Phase: D7
- Branch: `codex/wp71-simple-ui` (base: `origin/dev`)
- Depends on: none
- Role: implementer

## Goal
Today's console (`apps/web/app/page.tsx`, `apps/web/app/components/canonical/*`) shows jargon
("LIVE — canonical revision", "Teknik görünümler", endpoint badges like `GET /v1/documents`,
"Sağlayıcılar", "Veri sözleşmesi"), repeats "Düzenlenebilir · Kaynakta göster · Düzenle" on every
row and shows many "Başlıksız görsel". Make it clear for hotel staff.

## Tasks
1. Navigation: **Belgeler** (list, upload, status in one word: Hazır / İnceleme gerekiyor / Hata),
   **Belge** (tabs: Oku, Geçmiş), **Bilgi** (placeholder cards: Odalar, Restoranlar, Etkinlikler —
   "yakında"). Everything else (jobs, providers, data contract, raw JSON, endpoint badges) moves
   behind a **Geliştirici modu** switch (remembered in localStorage).
2. Rows: edit/"kaynakta göster" actions appear on hover/focus, not as repeated text.
3. Images without a description show "Açıklama yok — ekle" instead of "Başlıksız görsel".
4. Plain Turkish copy; no API paths or internal ids in the default view.
5. Keep all existing behavior reachable; do not change API calls.

## Acceptance criteria
- [ ] `cd apps/web && npm ci && npm run build` passes (TypeScript included).
- [ ] Report lists before/after for each screen in words, and anything you could not verify.
- [ ] No API/backend changes.
