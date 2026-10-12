# wp118-docling-structure-settings — Turn on the Docling features our structure needs

- Özet: Docling'in PDF başlık seviyesi kurtarmasını aç, TXT ve Markdown dosyalarını kendi okuyucumuz yerine Docling'den geçir, Docling'in tablo hücresi başlık bilgisini (sütun başlığı, satır başlığı, bölüm satırı) kanonik modelde koru.
- Model: derin
- Engine: codex
- Phase: D21
- Branch: `codex/wp118-docling-structure-settings` (base: `origin/dev`)
- Depends on: WP100, WP114, WP117 (merged)
- Role: implementer
- Owner: Porygon (codex)

## Why (WP117 measurement, 2026-10-12)

- Docling returns every PDF heading at `level=1` because `PdfPipelineOptions.heading_hierarchy_options`
  (`HeadingHierarchyOptions`) is not enabled in our profiles; lists attach to the wrong heading, floors and
  categories mix.
- TXT files go through our own `deterministic-text` parser, so Docling's structure (headings, lists) is missing:
  a 12-TXT company had 0 structural units.
- `_docling_cells` drops Docling's `TableCell.column_header`, `row_header`, `row_section` flags.

## Read first

`.agents/skills/docling/SKILL.md` and `references/python-sdk.md` ("Recovering heading levels", Markdown/TXT input),
ROADMAP decisions 18–21, `docs/plan/DOCLING-REUSE.md`, `apps/worker/docgrain_worker/docling_profiles.py`,
`structural.py`, `canonical_mapper.py`, the canonical `TableCell` model (schema 0.6.0 `source_attributes`).

## Goal

1. Enable heading hierarchy recovery in the default profile for PDFs (exact option names from the skill and the
   installed Docling 2.130 — the lead can run `python -c` in the worker image for you). Bump the profile digest.
2. TXT (and Markdown) through Docling's Markdown backend (Docling lists `md, markdown, txt, text, …` under MD).
   Keep exact text: compare word recall with the old path on the fixtures (must stay 100 %). The old
   `deterministic-text` path stays in place marked "KULLANILMIYOR (karar 18)".
3. Keep `column_header`, `row_header`, `row_section` per table cell in the canonical snapshot (`source_attributes`
   or the schema's own fields) and expose them to `structure_units` (WP117) and `structure_context` (WP114).
4. Measure: `benchmarks/docling_profiles.py --profiles C_tesseract` on the synthetic corpus and the lead runs
   `benchmarks/structure_coverage.py` before/after on the live stack.

## Rules

Never delete code (mark it unused). Grep the installed Docling for every option before use. No network in tests.

## Acceptance criteria

- [ ] A synthetic PDF with nested headings yields levels > 1; a TXT with headings and bullet lists yields
      `SectionHeaderItem`/`ListItem` structure and 100 % word recall; table cell header flags reach the canonical
      snapshot.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the lead's live commands.
