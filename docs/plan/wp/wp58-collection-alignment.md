# wp58-collection-alignment — one name per kind of list, inside and across companies

- Özet: Keşif aynı tür listeye farklı adlar veriyor (pools / swimming_pools, rooms / room_types, dining_venues / restaurants); öneriyi onaydan önce ortak sözlüğe hizalayıp aynı anlamdaki listeleri birleştir.
- Model: derin
- Engine: agy
- Phase: D4
- Branch: `codex/wp58-collection-alignment` (base: `origin/dev`)
- Depends on: wp57, wp48 (taxonomy), merged
- Role: implementer

## Problem (lead run, 2026-10-06, four real workspaces)

- Inside one workspace: `pools` and `swimming_pools`; `rooms` and `room_types` proposed side by side.
- Across workspaces: `dining_venues` vs `restaurants`, `events` vs `activities` vs `shows`/`theme_nights`.
Consistency across companies is a product goal (ROADMAP decision 13), so keys must converge.

## Tasks

1. A canonical vocabulary built from `packages/records/taxonomy.json` (wp48) plus a synonyms map
   (`packages/records/collection_synonyms.json`): canonical key → synonyms in EN snake_case
   (e.g. `pools`: swimming_pools, pool_areas; `rooms`: room_types, accommodation; `restaurants`:
   dining_venues, outlets_dining; `activities`: events, shows, theme_nights, entertainment).
   Unknown keys stay as discovered (companies are not only hotels).
2. `align_proposal(proposal) -> proposal`: rename to the canonical key, merge collections that land
   on the same key (union of fields by key, keep field conflicts as alternatives, keep all examples and
   evidence), record `aliases` on the merged collection. Run it in `discover` before writing
   `schema.proposed.json` (flag `--no-align` to skip).
3. Field names: same idea for frequent field synonyms inside a collection (`service_hours` /
   `opening_hours`, `capacity` / `max_occupancy`), conservative list.
4. Tests with synthetic proposals: the four problems above merge correctly; a non-hotel workspace
   (clinic `services`) is untouched; quotes stay verified after merge.

## Acceptance criteria

- [ ] `.venv/Scripts/python -m pytest -q tests/unit -p no:cacheprovider --basetemp=.lead/pt` and
      `ruff check apps packages tests` pass — run pytest in the FOREGROUND (no background tasks).
- [ ] Report in Turkish: the map you chose and why, and what you could not verify.

## Notes

- Sandbox: no network, no installs, no real customer documents; synthetic fixtures only.
