# wp55-bilgi-polish — Bilgi screen speaks the user's language

- Özet: Bilgi ekranında teknik alan adları (bed_types, capacity) ve çevrilmemiş liste adları (properties, facilities) yerine Türkçe etiketler, kartlarda kayıt sayısı ve listede kayıt adları görünsün.
- Model: standart
- Engine: agy
- Phase: D7
- Branch: `codex/wp55-bilgi-polish` (base: `origin/dev`)
- Depends on: wp54 (merged)
- Role: implementer

## Goal

The Bilgi screen (`apps/web/app/components/information/information.tsx`) works on real data but shows
code names. A hotel employee must read plain Turkish everywhere.

## Tasks

1. Collection cards: Turkish label for every collection key (`rooms` Odalar, `outlets` Mekanlar
   (Restoran/Bar), `activities` Etkinlikler, `facilities` Olanaklar, `policies` Kurallar ve Politikalar,
   `contacts` İletişim, `properties` Tesis Bilgileri, `service_prices` Hizmet Fiyatları) and the record
   count on each card; unknown keys fall back to a humanized label (`snake_case` → "Snake case").
   Keep the label map in one small module so wp52 (discovered collections) can replace it later.
2. Collection view: a list of records first (the record's `name` or first text field as the title,
   a one-line summary), then the record detail on click — not all records' fields stacked.
3. Field labels: Turkish labels for the known fields (e.g. `bed_types` Yatak tipleri, `capacity`
   Kapasite, `features` Özellikler, `view` Manzara, `name` Ad, `size_m2` Büyüklük (m²), `opening_hours`
   Açılış saatleri, `price` Fiyat …); unknown fields humanized. No snake_case in the default view.
4. Keep everything else from wp54 (badges, Önizleme/Onaylı, Kaynakta göster, Geliştirici modu).

## Acceptance criteria

- [ ] `npx tsc --noEmit -p apps/web` clean (the lead runs `npm run build`).
- [ ] No snake_case keys visible in the default view on real data.
- [ ] Mobile 390 px without horizontal overflow (describe how you ensured it).
- [ ] Report in Turkish with the before/after for each screen.

## Notes

- Real data is published locally: `GET http://localhost:8000/v1/workspaces/ws_local/revisions` — you
  cannot call it from the sandbox; use the shapes in `tests/unit/test_records_api.py` and
  `packages/records/docgrain_records/export.py`.
- Web only; no API changes.
