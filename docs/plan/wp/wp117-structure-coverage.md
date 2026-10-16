# wp117-structure-coverage — How much of a company's data do Docling's structures already give us?

- Özet: Model kullanmadan, Docling'in tablo, liste, başlık, anahtar–değer ve Excel sayfası yapılarından her şirket için kaç koleksiyon ve kayıt çıktığını ölç; benzer yapıları tek koleksiyonda toplamanın ilk halini kur; bugünkü model tabanlı sonuçla karşılaştır.
- Model: derin
- Engine: codex
- Phase: D21
- Branch: `codex/wp117-structure-coverage` (base: `origin/dev`)
- Depends on: WP100 (Docling default reader), decision 21
- Role: implementer
- Owner: Bulbasaur (codex)

## Why (decision 21, 2026-10-12)

Collections should come first from the structure Docling already returns, merged across documents into one
collection per kind of list; the model is only a fallback. Before building it, measure on the 19 test companies
how much structure-only covers. Verified Docling 2.130 / docling-core 2.101 building blocks: `TableItem` with
`TableData.table_cells` (`text`, `column_header`, `row_header`, `row_section`, spans, `bbox`) and
`export_to_dataframe()`; `ListGroup`/`ListItem`; `SectionHeaderItem.level` and the body tree; `KeyValueItem` and
groups `KEY_VALUE_AREA`, `FORM_AREA`, `SHEET`, `SLIDE`, `CHAPTER`, `SECTION`; `ProvenanceItem(page_no, bbox,
charspan)`.

## Goal (measurement first — no change to the production pipeline)

1. A read-only module `packages/records/docgrain_records/structure_units.py` that, from a stored DoclingDocument
   JSON (the per-version Docling artifact the worker keeps; find where it is stored — `legacy_json` /
   `docling_document` artifact — read the code, do not guess), lists structural units: table (header row(s) →
   field names, rows → items, first/row-header column → item name, cell provenance), list (heading above → title,
   items), key-value area (keys → fields), sheet (sheet name, its tables). Each unit has a candidate name (caption,
   nearest heading, sheet name) and evidence for every cell/item.
2. A first deterministic grouping `group_units`: units across documents of one company join one candidate
   collection when their normalized field sets overlap strongly (e.g. Jaccard ≥ 0.6 after normalization) or their
   names match after normalization; inside a candidate collection, items with the same normalized name become one
   candidate record. Ambiguous joins are listed, not decided. Pure functions, no model, no network.
3. `benchmarks/structure_coverage.py` (the lead runs it on the live stack): for each workspace — units by type,
   candidate collections (names, field lists, item counts), and comparison with the current published model-based
   revision: share of published records whose name appears among structure items of the same/similar collection,
   share of published field values also present in structure cells, and collections present only in one of the two.
   JSON + Markdown, file names only in private output.
4. Tests on synthetic DoclingDocuments built with docling-core types (two documents: a table "Restaurant | Hours"
   and a sheet "F&B saatleri" with "Restoran | Açılış | Kapanış"; a bullet list under "Havuzlar"; a key-value area).

## Rules

Do not change the existing pipeline or delete code (decision 21 / user rule). No model calls. Host tests run
without Docling installed (use docling-core types, which are installed on the host; check) — if docling-core is not
importable on the host, build plain-dict fixtures matching its JSON and say so.

## Acceptance criteria

- [ ] Synthetic tests: the two restaurant units join one collection, the same restaurant becomes one candidate
      record with both sources, the pool list becomes a collection, the key-value area yields fields.
- [ ] `benchmarks/structure_coverage.py --help` and a dry run on fixtures work.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the lead's live command.
