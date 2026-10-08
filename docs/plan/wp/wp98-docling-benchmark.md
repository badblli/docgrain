# wp98-docling-benchmark — Configurable Docling profiles and a benchmark before we delete our parser code

- Özet: Docling'in kendi tablo, okuma sırası, OCR, güven raporu ve görsel ayarlarını seçilebilir profiller hâline getir; bizim belgelerimizde bugünkü yolla karşılaştıran ölçüm betiğini yaz, böylece hangi kodumuzu sileceğimize sayılarla karar verelim.
- Model: derin
- Engine: codex
- Phase: D18
- Branch: `codex/wp98-docling-benchmark` (base: `origin/dev`)
- Depends on: none
- Role: implementer
- Owner: Porygon (codex)

## Read first

`docs/plan/DOCLING-REUSE.md` (decision 18 study), sections 1 and 4. ROADMAP decision 18.

## Goal

1. `apps/worker/docgrain_worker/structural.py::_docling` builds its `DocumentConverter` from a named,
   versioned reading profile instead of hard-coded options. Profiles (use the exact Docling 2.130 option
   names: check the installed package, do not guess):
   - `A_current`: the current behaviour, byte for byte (default until the lead switches).
   - `B_docling`: our native fidelity, reading-order and missing-table passes off; TableFormer ACCURATE with
     cell matching; EasyOCR tr/en with threshold 0.5; Docling reading order; Docling confidence captured.
   - `C_tesseract`: B with `TesseractCliOcrOptions(lang=["tur","eng","deu","rus"])`.
   - `D_fullpage`: C with `OcrMode.FULL_PAGE` for scanned pages and images (JPG/PNG), picture classification on.
   - `E_vlm`: D plus picture description and hard-page VLM through an OpenAI-compatible endpoint given by
     arguments (base URL, model, key env name). Never runs unless explicitly requested with a key.
   The profile id and its option digest go into the processing spec so revisions stay reproducible.
2. Capture the Docling confidence report (`ConversionResult.confidence`: per-page ocr/layout/parse scores,
   mean and low grade) into the canonical artifacts.
3. `pdf_geometry.normalized_pdf_box`: tolerate small out-of-page boxes (clip within a tolerance) behind a flag,
   so its effect on `bbox_unresolved` can be measured on its own.
4. Benchmark script `benchmarks/docling_profiles.py`: for a folder of company subfolders, convert every file
   with each requested profile (in-process, in the worker image) and write one JSON plus a Markdown table with,
   per file and profile: word recall against the source text layer (PDF via PyMuPDF, DOCX via XML runs joined,
   XLSX cells, TXT), counts of blocks/tables/pictures, resolved bbox ratio and `bbox_unresolved`, pages with a
   Docling low grade versus our hard-page codes, seconds per page, peak RSS, VLM calls (E only). File names
   appear only in the private output; the script contains no customer data.
5. Worker Dockerfile: add `tesseract-ocr` with the `tur`, `deu`, `rus` and `eng` language packs. The lead builds.

## Rules

- No deletions in this WP: our modules stay; profiles only switch them off.
- Before you import or use a Docling option, grep the installed package that it exists in 2.130. List any
  option you could not find.
- No network in tests. Tests use small synthetic files: a 2-page PDF with columns and a table, a scanned image
  page, a DOCX, an XLSX with a percent and a date cell.

## Acceptance criteria

- [ ] `A_current` output is identical to dev on the existing test fixtures (golden comparison test).
- [ ] Profiles B–D convert the synthetic files; the confidence report is stored; the profile id is in the spec.
- [ ] `benchmarks/docling_profiles.py --profiles A_current,B_docling --root <dir> --out <dir>` runs on the
      synthetic fixtures and produces the table.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean.
- [ ] Report (Turkish): the exact command for the lead to run in the worker container on `data/sources`, the
      options you could not verify, and the expected runtime.
