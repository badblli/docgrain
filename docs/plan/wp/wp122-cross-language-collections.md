# wp122-cross-language-collections — The same kind of list in different languages is one collection

- Özet: Türkçe "Restoranlar", İngilizce "A la carte restaurants", Almanca "Restaurants" ve Rusça "Рестораны" tabloları aynı tür liste olduğunda tek koleksiyon olsun; alanlar ve kimlik sütunu uyuşuyorsa kendiliğinden, emin değilse bir kez "Bu iki liste aynı şeyi mi anlatıyor?" diye sorulsun; ardından WP115 aynı yerleri ("Balık restoran" / "Fish restaurant") birleştirsin ya da sorsun.
- Model: derin
- Engine: codex
- Phase: D21
- Branch: `codex/wp122-cross-language-collections` (base: `origin/dev`)
- Depends on: WP119 (structure-first collections), WP115 (cross-language duplicates) — both merged
- Role: implementer
- Owner: Porygon (codex)

## Why (lead live check, 2026-10-18)

Synthetic workspace with two Markdown documents: a Turkish table under "Restoranlar"
(`Restoran | Açılış saatleri | Mutfak`) and an English table under "A la carte restaurants"
(`Restaurant | Opening hours`). Structure-first built **two** collections (`restaurants`,
`a_la_carte_restaurants`) and asked no "same list?" question, although `field_key()` maps both tables to the same
keys (name column, `hours`). WP115 only merges records inside one collection, so "Balık restoran" /
"Fish restaurant" were never merged or asked.

Cause (lead reading): `structure_units.group_units` compares **raw** normalized header labels (`norm(label)`) and
raw unit names. "açılış saatleri" vs "opening hours", "restoranlar" vs "a la carte restaurants" and
"balık restoran" vs "fish restaurant" share nothing, so there is no strong and no weak signal. The English-key
vocabulary (`FIELD_KEYS`, `COLLECTION_KEYS`) lives in `structure_records.py` and is used only after grouping.
Also: `_slug()` keeps only `[a-z0-9]`, so Cyrillic headers/titles become `value` / `items`.

## Read first

`packages/records/docgrain_records/structure_units.py` (`group_units`, `_signals`, `_strong`, `_collection`),
`structure_records.py` (`FIELD_KEYS`, `COLLECTION_KEYS`, `field_key`, `collection_key`, `_apply_answers`,
`build_structure_plan`, signatures), `collection_merge.py`, `place_names.py` (WP115 TR/EN/DE/RU name keys),
`apps/worker/docgrain_worker/records_pipeline.py` (where the structure plan and WP115 run),
`tests/unit/test_structure_first.py`, `tests/unit/test_structure_units.py`, ROADMAP decision 21.

## Goal

1. **Shared vocabulary module** `packages/records/docgrain_records/structure_vocab.py`: move `FIELD_KEYS` and
   `COLLECTION_KEYS` there (re-export from `structure_records` so existing imports keep working) and extend them
   with German and Russian entries for the same concepts (e.g. Öffnungszeiten / часы работы → hours, Preis / цена →
   price, Restaurants / Рестораны / Restaurant / ресторан → restaurants, Bars / бары → bars, Zimmer / номера → rooms …).
   Bounded, documented, testable; no general translation, no model. Make Cyrillic keys/slugs usable (a small
   transliteration in `_slug`, or keep Unicode letters — choose and justify; keys must stay valid identifiers for
   the runtime).
2. **Collection head noun**: a title maps to a known collection key when it is a known key or ends with one
   ("A la carte restaurants", "Ana restoranlar", "Unsere Restaurants" → restaurants). Titles naming two kinds
   ("Restaurants & Bars") map to none.
3. **Grouping signals across languages** in `group_units` (comparison only; source labels and values are never
   replaced):
   - canonical field keys per unit (vocabulary key, else the normalized label), with the item-name column counted
     as the identity column;
   - canonical collection key per unit name;
   - cross-language item overlap using `place_names` comparison keys ("Balık restoran" / "Fish restaurant" → fish).
   Decision:
   - **Join automatically** when canonical collection keys are equal (both known) AND the canonical fields agree
     (Jaccard ≥ `FIELD_JACCARD` incl. identity column) — or equal collection keys plus translated item overlap.
   - **Never join** when both canonical collection keys are known and different (restaurants vs bars), even when the
     canonical fields are identical (`name, hours`); do not create new questions for that case either.
   - **Ask once** (existing `collection_merge` question, `weak_overlap`) when canonical fields agree but at least one
     side has no known collection key, or keys agree but fields only overlap weakly.
   - Same-language behaviour and every existing test stay unchanged; `would_bridge_collections` logic unchanged.
4. Unit/pair **signatures stay as they are** (raw labels), so earlier answers keep applying.
5. **Field keys after a join**: a TR and an EN/DE/RU table joined into one collection must land on one field key per
   concept (`hours`, not `acilis_saatleri` + `opening_hours`). Before adding new TR/EN entries that change an
   existing `field_key()` output (e.g. Mutfak → cuisine), check what a changed key does to a workspace that already
   has an accepted schema on the next records run (aliases? lost answers?) and report it; if it would break
   accepted data, keep the old output for already-known labels and say so.
6. **End to end**: in the pipeline test setup, the joined collection lets WP115 run: same place with an agreeing
   non-name field (same hours) is merged; a translated pair with a conflicting field becomes a `duplicate` question.

## Rules

Never delete replaced code (mark it `KULLANILMIYOR (karar 18)`, copy to an `unused/` folder if a module is
replaced). No real model in tests. Do not touch `merge.py` or `structure_context.py` (another WP works there).
Synthetic data only; no customer names.

## Acceptance criteria

- [ ] New tests (e.g. `tests/unit/test_structure_cross_language.py`) with synthetic Docling JSON + contexts:
  - TR "Restoranlar" (`Restoran | Açılış saatleri | Mutfak`) + EN "A la carte restaurants"
    (`Restaurant | Opening hours`) → one `restaurants` collection, no `collection_merge` question, one `hours` field;
  - DE "Restaurants" (`Restaurant | Öffnungszeiten`) + RU "Рестораны" (`Ресторан | Часы работы`) join the same
    collection; Russian keys/labels are not `value` / `items`;
  - TR "Barlar" (`Bar | Açılış saatleri`) + EN "Restaurants" (`Restaurant | Opening hours`) stay two collections,
    no question;
  - EN "Our venues" (`Venue | Opening hours`) + TR "Restoranlar" → exactly one `collection_merge` question; "same"
    joins it now and on the next run (remembered), "different" is never asked again;
  - pipeline: "Balık restoran" / "Fish restaurant" with the same hours → one record with both sources; with
    different hours → one `duplicate` question.
- [ ] `.venv/Scripts/python -m pytest -q` green, `.venv/Scripts/python -m ruff check .` clean.
- [ ] Report in Turkish: cause, design, what changed in field keys for existing workspaces, the lead's live
      commands (rebuild + the two synthetic `.md` files).

## Notes

Live check notes (lead): side-session notes `live-check-2026-10-18.md`. The lead rebuilds Docker and repeats the
live check after merge.
