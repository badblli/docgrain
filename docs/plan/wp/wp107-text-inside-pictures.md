# wp107-text-inside-pictures — Keep everything plain Docling reads (text inside pictures, designed menus)

- Özet: Docling arka plan görseli olan bir sayfayı tek bir resim sayınca, sayfanın kendi metin katmanındaki yazılar (ör. şarap menüsündeki şarap adları ve fiyatlar) kayboluyor; bu metni resmin altında kaynaklı olarak koru.
- Model: derin
- Engine: codex
- Phase: D18
- Branch: `codex/wp107-text-inside-pictures` (base: `origin/dev`)
- Depends on: WP100, WP105 (merged)
- Role: implementer
- Owner: Porygon (codex)

## Why (lead reading report, 2026-10-09, 19 businesses / 91 files)

PDF word recall is 97.4 % overall, but one wine menu PDF keeps 2.8 %: its text layer is clean (3,218 characters,
e.g. "NO-1- Lamberti 75 cl 30 €", "Kavaklıdere Sultaniye 75 cl 27 €") yet the canonical snapshot has only
2 text blocks and 1 asset: Docling's layout classified the page (designed with a background image) as one
picture, and the text cells inside the picture region were not emitted. The same pattern is likely in other
designed brochures and menus.

## Goal

1. Find where the text goes: check whether Docling 2.130 keeps the programmatic text cells of a picture region
   (e.g. as children of the `PictureItem`, in `ConversionResult.pages[*].cells`, or not at all) and whether a
   pipeline option controls it. Read the installed Docling source in the worker image (the lead can run commands
   for you; list what you need). Do not guess option names.
2. Prefer a Docling option if one exists. Otherwise, in our mapper: for each picture region on a page with a text
   layer, emit the text-layer cells inside that region as text blocks (reading order inside the region, bbox
   provenance, `content_origin=text_layer_in_picture`), so the picture stays an asset and its text is kept.
   Only programmatic text-layer cells, never OCR guesses, on this path.
3. Re-measure with `benchmarks/docling_profiles.py --profiles C_tesseract` on a synthetic PDF built in the test
   (a full-page background image with real text on top) and report the change.

## Rules

Do not delete our code (decision 18 rule: retire and mark). No network in tests.

## Acceptance criteria

- [ ] Synthetic "text over background picture" PDF keeps ≥ 95 % of its words with bbox provenance.
- [ ] Ordinary PDFs unchanged (existing tests and fixtures).
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the lead's live check command.

## Lead experiment (2026-10-09) — the loss is in OUR integration, not in Docling

`.lead/menu_experiment.py` (private) ran Docling 2.130 directly (`DocumentConverter` + `PdfPipelineOptions`,
`TesseractCliOcrOptions(lang=[tur, eng, deu, rus])`, table structure off) in the worker image:
- Designed menu without a text layer, page 3: clean bilingual text ("Çorba Soup … Füme Domates Çorbası …
  Havuç, soğan, kereviz, sarımsak … Soğuk Başlangıçlar … Dana Carpaccio …"), 469 words in 9 s. Our pipeline
  produced "Oo", "6©", "®" for the same file. The document had 3 pictures with 1–3 text children each.
- Wine menu: plain Docling emits 37 text items and 0 pictures with the full wine list; our pipeline emitted one
  picture + 2 blocks (2.8 % recall).

So: (1) diff our `C_tesseract` options (`apps/worker/docgrain_worker/docling_profiles.py`, `structural.py`,
WP105 `BudgetedPipeline`/`BudgetedOcr`) against this plain configuration and find which option or wrapper
changes the result; (2) check `canonical_mapper.py` for dropped `PictureItem` children / text items whose
parent is a picture; (3) fix so our canonical text matches plain Docling on these files (word count within 5 %).
The lead can run the experiment and the benchmark in the worker image for you; describe the command.
