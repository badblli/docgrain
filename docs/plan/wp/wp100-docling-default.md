# wp100-docling-default — Make Docling + Tesseract the default reader and delete what it replaces

- Özet: Ölçüm Docling + Tesseract profilinin (C) bizim okuma kodumuzdan hiçbir dosyada kötü olmadığını, üç kat hızlı olduğunu ve 2.893 kutu sorununu sıfırladığını gösterdi; C'yi varsayılan yap ve yerini aldığı kendi PDF/DOCX/kalite kodumuzu sil.
- Model: derin
- Engine: codex
- Phase: D18
- Branch: `codex/wp100-docling-default` (base: `origin/dev`)
- Depends on: WP98 (merged)
- Role: implementer
- Owner: Porygon (codex)

## Evidence (lead benchmark 2026-10-08, 64 files of 12 test companies, worker image)

| | A_current | B_docling | C_tesseract | D_fullpage |
|---|---|---|---|---|
| PDF word recall (text layer) | 94.8 % | 93.6 % | 95.7 % | 88.0 % |
| `bbox_unresolved` | 2,893 | 0 | 0 | 0 |
| Complete files | 27 | 32 | 29 | 16 |
| JPG blocks | 855 | 668 | 1,540 | 1,618 |
| Total time | 49 min | 48 min | 16 min | 18 min |

C is never more than 1 point below A on any file and is 6.6–11.4 points better on three PDFs. D hurts
digital PDFs; full-page OCR belongs only to pages without a text layer and to image files.
Decision 18 rule: our module goes when Docling is at most 1 point below it.

## Goal

1. New default reading profile `C_tesseract` (keep the profile id and option digest in the processing spec).
   Image files (JPG/PNG) and PDF pages without a text layer use full-page OCR (the D setting) inside the same
   default; digital PDF pages keep layout-region OCR. If Docling 2.130 cannot switch OCR mode per page, apply
   full-page OCR per file only when the PDF has no text layer at all, and list this limitation.
2. Delete what C replaces (see `docs/plan/DOCLING-REUSE.md` section 4, step 3):
   `pdf_fidelity.py`, `pdf_reading.py`, `structural.py::_pdf_missing_tables`, the native DOCX path
   (`native_office.docx_items`, `_docx_paths`) and the native XLSX completion — keep a thin number/date/percent
   formatter for XLSX cells. Replace `quality.py` / `_tag_ocr` hard-page signals with the Docling confidence
   report (low/poor grade pages) and keep the existing issue codes the web shows, mapped from it.
   Remove the old Gemini page path (`main.py::gemini_extraction`, `render_pages`, `document_converter()`,
   `vision.GeminiPageExtractor`) and the `google-genai` dependency if nothing else uses it (grep first).
3. Keep profiles A/B/D/E selectable for re-measurement but A may now point to the removed code only if it
   still exists; if A cannot run after the deletions, remove profile A and say so.
4. Delete or rewrite the tests that only covered removed code; keep coverage for the new default with the
   synthetic corpus from WP98. Update ADRs: add a new ADR "Docling reads documents (decision 18)" that
   supersedes the fidelity/visual ADRs it replaces (0018–0020, 0023 as applicable — read them).
5. Report how many lines were removed.

## Rules

- Grep before deleting: anything still imported elsewhere is either migrated or kept with a reason.
- No network in tests. Tailwind/web untouched.

## Acceptance criteria

- [ ] Default conversions of the synthetic corpus pass; DOCX/XLSX/TXT keep 100 % word recall; XLSX percent/date
      cells keep their display format.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean.
- [ ] Report (Turkish): removed files and line count, kept pieces with reasons, the command for the lead to
      re-run `benchmarks/docling_profiles.py --profiles C_tesseract` in the worker image.
