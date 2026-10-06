# wp52-schema-driven-records — Extract, merge and publish from the discovered schema

- Özet: Çıkarım, birleştirme ve JSON yayınını sabit otel modelleri yerine keşfedilen şemaya göre çalıştır; her şirket kendi koleksiyonlarını alsın.
- Model: derin
- Phase: D4
- Branch: `codex/wp52-schema-driven-records` (base: `origin/codex/wp51-collection-discovery`)
- Depends on: wp51, wp43 (publication modes), wp48 (value normalization)
- Role: implementer

## Tasks
1. Dynamic record models from an accepted `schema.v<N>.json` (JSON Schema → validation), used by
   extraction (section-wise + completeness passes per collection), matching and merge.
2. Publication: one JSON per discovered collection key (`<key>.json`), preview/approved modes,
   `?lang=` with EN-first fallback, `_meta` provenance; compact AI context per collection with
   explicit conflicts.
3. Keep every guarantee: verified quotes, source pins, conflicts visible, no silent merges.
4. Tests: two synthetic companies with different schemas produce different collections.

## Acceptance criteria
- [ ] Ruff + pytest clean; old hospitality fixtures still pass through the dynamic path.
