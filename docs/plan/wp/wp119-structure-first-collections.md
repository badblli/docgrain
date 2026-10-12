# wp119-structure-first-collections — Build collections from Docling structure in the real pipeline

- Özet: Bilgileri çıkar önce Docling'in tablo, liste, anahtar–değer ve Excel sayfalarından koleksiyonları ve kayıtları modelsiz kursun, benzerlerini belgeler arasında tek koleksiyonda birleştirsin; model yalnızca yapısı olmayan bilgi için ve şirket modeli açıksa devreye girsin.
- Model: derin
- Engine: codex
- Phase: D21
- Branch: `codex/wp119-structure-first-collections` (base: `origin/dev`)
- Depends on: WP117 (structure units + grouping), WP114 (structure context), WP111 (review rules); WP118 improves
  inputs but is not required to start
- Role: implementer
- Owner: Charizard (codex)

## Why (decision 21 + WP117 measurement, 2026-10-12)

On a mixed-format company 96 % of the record names and 98 % of the values the model-based pipeline published are
already present in Docling's structure; on designed brochures 48–69 %. Structure-first is deterministic, free,
sector-independent and keeps every value tied to a table cell or list item.

## Read first

`.agents/skills/docling/SKILL.md` + references, ROADMAP decisions 18–21, `packages/records/docgrain_records/
structure_units.py` (WP117), `structure_context.py` (WP114), `auto_accept.py`/`normalize.py` (WP111),
`apps/worker/docgrain_worker/records_pipeline.py`, `benchmarks/structure_coverage.py`.

## Goal

1. New pipeline stage before discovery: load each pinned document's DoclingDocument, build structure units, group
   them into collections (WP117 `group_units`), and turn candidate records into our `ExtractionResult`/records with
   evidence = the cell/item provenance (document, ref, page, bbox, header labels). Field keys: normalized English
   snake_case from header text where obvious, otherwise the normalized header; Turkish/source labels kept.
2. Robustness found by WP117: header rows mislabelled by Docling in some DOCX tables (detect when "header" cells
   look like data — e.g. the row repeats in the body pattern); transposed tables (items in columns) — detect and
   transpose; lists named from numbered section headings must not all fall into one giant collection (use the
   nearest specific heading; WP118 levels help).
3. Ambiguous groupings (WP117 `weak_overlap`, `would_bridge_collections`) become one question each: "Bu iki liste
   aynı şeyi mi anlatıyor?" (new question kind `collection_merge`), answer remembered for later runs/versions.
4. Model fallback: discovery + extraction run only for documents/sections without usable structure (no units, or
   units cover < a threshold of the document text), only when the workspace model is on; their records join the
   same collections via the existing match/merge. Model off → structure-only results, with a note listing
   documents that need the model.
5. Everything after that is unchanged: match/merge, auto-accept (decision 20), conflicts, publish, Dene/API.
6. Measure with `benchmarks/structure_coverage.py` and `benchmarks/consolidation_report.py` on two live companies
   (the lead runs): records, collections, conflicts, duplicates, unsupported (must be 0), model calls (should drop).

## Rules

Never delete code (model-based discovery stays as the fallback path). No real model in tests.

## Acceptance criteria

- [ ] Synthetic: a table in a PDF and a sheet in an XLSX describing the same restaurants become one collection with
      one record per restaurant and both sources; a conflicting hour becomes a conflict question; a weak overlap
      becomes a `collection_merge` question; a prose-only document triggers the model path only when enabled.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the lead's live commands.
