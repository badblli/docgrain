# wp67-identity-duplicates — the right record title, and duplicates asked as questions

- Özet: Kayıtların başlığı doğru alandan gelsin (SSS'de soru, odada ad) ve aynı şeyin iki kaydı ("King Suite" / "King Suit Oda") birleştirme önerisi olarak sorulsun: "Bu iki kayıt aynı mı?"
- Model: derin
- Engine: codex
- Phase: D4
- Branch: `codex/wp67-identity-duplicates` (base: `origin/dev`)
- Depends on: wp64 (merged)
- Role: implementer

## Findings (lead, real workspaces, values withheld)

1. FAQ records are titled by their answer ("Evet var.", "İlgili departmana bilgi…"): the runtime picks
   `name`, else the first field; for FAQs the first field is the answer. 5 of 7 open questions in one
   workspace are FAQ records with such titles.
2. Same entity, several records: e.g. a suite appears as "King Suite" and "King Suit Oda", another as
   "Prime Suit", "Prime Suite" and "Prime Suit Oda". The duplicate report counts 11 likely groups in one
   workspace.

## Tasks

1. Identity field choice at schema acceptance (`discovery_store.accept_schema` / `runtime`): prefer
   `name`, `title`, `question`, `term`, `label` (EN keys) over the first field; record the choice as
   `identity` in the accepted schema; old schemas keep their behaviour. FAQ questions become titles.
2. Duplicate candidates inside a collection after merge: normalized-name similarity (casefold, Turkish
   characters, stop words like oda/room/suite variants, token sort), plus field overlap (same capacity,
   same size…) — conservative score; never auto-merge.
3. New question kind `duplicate`: "Bu iki kayıt aynı mı?" with both records side by side (title, 3–4
   key fields, sources) and answers `{"same": true}` (merge: union of fields with evidence, conflicts
   become normal questions) / `{"same": false}` (remember, never ask again for this pair) / skip.
   Each answer writes and publishes a new revision (same rules as wp59). Summary gains `duplicates`.
4. Web: render the `duplicate` card with the existing Tailwind/shadcn components (two columns,
   "Aynı kayıt" / "Farklı kayıtlar" / "Sonra sor"); no new CSS files.
5. Tests with synthetic data shaped like both findings.

## Acceptance criteria

- [ ] `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass.
- [ ] `npx tsc --noEmit -p apps/web` clean (lead runs the build and checks on real data).
- [ ] Report: before/after on synthetic data, and the command for the lead's real re-run.
