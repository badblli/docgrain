# Docling reuse study (decision 18) — what we leave to Docling, what stays ours

Date: 2026-10-08. Two independent studies (Docling core + Serve; Docling Graph) read our code and the upstream
docs/source. Nothing is deleted before the benchmark below decides it. Unverified points are marked.

## 1. Docling core — verdicts (pinned `docling==2.130.0`, latest 2.135.0)

We call Docling in one place (`apps/worker/docgrain_worker/structural.py::_docling`) with EasyOCR tr/en,
`PDF_AWARE_LAYOUT_REGIONS`, `confidence_threshold=0.0`, 2 CPU threads; table mode, picture
description/classification, VLM and the confidence report are unused. `main.py::document_converter()` is an
older second conversion without OCR.

| Docling capability | Our duplicate | Verdict |
|---|---|---|
| TableFormer ACCURATE + `do_cell_matching` | `pdf_fidelity.py`, `structural.py::_pdf_missing_tables` | REPLACE |
| Reading-order model (updated 2.132) | `pdf_reading.py` (XY-cut, column split) | REPLACE |
| Confidence report per page (`ocr_score`, `layout_score`, `parse_score`, `mean_grade`, `low_grade`) | `quality.py`, `_tag_ocr`, WP97 hard-page detection | REPLACE the signal; KEEP the Turkish report/UI |
| OCR engines + `OcrMode` | `ocr.py`, `local_visual_ocr.py` | `ocr.py` WRAP (pinned profile); `local_visual_ocr.py` REPLACE |
| docling-core bbox / origin conversion | `pdf_geometry.py`, `canonical_mapper._locator` | WRAP; add tolerance (hypothesis: our strict box check causes most `bbox_unresolved`) |
| EXIF orientation (since 2.128) | `image_geometry.py` | WRAP; remove later |
| DOCX backend (headers/footers, footnotes, text boxes) | `native_office.py::docx_items`, `_docx_paths` | REPLACE |
| XLSX backend (sheets, merged cells, charts, images) | `_xlsx_items`, `native_office.py::xlsx_charts` | REPLACE, KEEP a thin number-format layer (Docling reads `data_only`, `str(value)`: dates/percent lose format) |
| Picture description (`PictureDescriptionApiOptions`) + classification | `selective_vision.py`, `visual_review.py` proposals, ADR 0023 proposal API, old `vision.py` | REPLACE proposal generation; KEEP human review record |
| VLM pipeline with remote OpenAI-compatible API (`ApiVlmOptions`) | WP97 `WorkspacePageExtractor`, `main.py::gemini_extraction`, `GeminiPageExtractor`, `google-genai` | REPLACE transport; DELETE the old Gemini path |
| Only hard pages to the VLM | WP97 page selection, budget, resume | KEEP (thin) — no page-level hybrid mode found in Docling (unverified) |
| Chunkers (Hybrid/Hierarchical) | `canonical/chunking.py` | KEEP now (lineage, stable ids), WRAP later |
| — | `canonical_mapper/writer/assets`, `output_writer`, `index_lifecycle`, `source_adapters`, `fidelity.py` (measurement), TXT | KEEP |

Recommended configuration (CPU, Docker): 4 threads, `document_timeout=600`, models baked at
`/opt/docling-models`, `generate_page_images=True` (`images_scale=2`), TableFormer ACCURATE. OCR for
TR/EN/DE/RU: EasyOCR cannot mix Latin and Cyrillic in one checkpoint and RapidOCR takes one language, so test
`TesseractCliOcrOptions(lang=["tur","eng","deu","rus"])` against current EasyOCR. Scans and images:
`OcrMode.FULL_PAGE` (hypothesis: the 9 MB JPG gave 2 chunks because layout treated it as one picture), plus
picture classification/description. Workspace model on (decisions 15/17): picture description and hard-page
VLM through the workspace's OpenAI-compatible endpoint; model off → `enable_remote_services=False`.
Gemini returns Markdown, not DocTags, so VLM pages get page-level provenance only.

Canonical format: keep ours (source versions, revision/spec digest, deterministic node ids — Docling
`self_ref` shifts between runs, provenance, review status, evidence, lineage). Store the DoclingDocument JSON
per revision as an immutable artifact and reference it from canonical nodes; the mapper becomes a thin adapter.

Docling Serve: not now (we need `ConversionResult` internals such as confidence; per-workspace keys would pass
through a second service; we already have a queue). docling-mcp: no — our MCP serves approved knowledge.

## 2. Docling Graph — verdicts (`docling-graph` 1.9.1, MIT)

Strong per-document template extraction plus a simple cross-document "graph fusion". It does not meet two
product guarantees: field-level verified evidence (our "zero unsupported fields") and asking a human on
conflict (it keeps the first value, or lets an LLM pick).

| Docling Graph | Ours | Verdict |
|---|---|---|
| Parsing via Docling | `structural.py` | already used |
| Chunking (`chunk_max_tokens`) | `sections.py` (§N keys tied to evidence checks) | KEEP for now |
| Pydantic templates, `graph_id_fields` | `runtime.py` (`WorkspaceSchema` → `create_model`) | WRAP possible (runtime template) |
| Template from docs/ontology | `discovery*.py`, `discovery_store.py` | KEEP (ours is per company, quote-verified, aligned, human-accepted) |
| LLM extraction (`direct`, `dense`) via LiteLLM | `extractor.py`, `model.py` | A/B benchmark, then maybe WRAP |
| Node-level provenance | `Evidence`, `verify_response`, `VersionedEvidence` | KEEP (ours verifies every field's quote) |
| In-document merge (last wins / LLM dedup) | `_coalesce_document_records` | KEEP (ours keeps conflicts as `needs_review`) |
| Entity ids (content hash; `--rekey` exists) | `merge.py` identity map, aliases | KEEP |
| Cross-document `merge` (keep-first, alias report) | `match.py`, `match_merge.py`, `merge.py` | KEEP; borrow ideas: keep losing values as variants, alias-candidate report, ignore whitespace/case/Unicode-only differences |
| Multi-value, schedules | `multivalue.py`, `schedule*.py` | KEEP |
| Review, questions, approved revisions | `review.py`, `duplicates.py`, `records_repository.py` | KEEP |
| Exports CSV/Cypher/Neo4j | `export.py`, `ai_access.py`, `packages/access` | KEEP; Cypher export of approved revisions optional later |
| Batch | worker queue, `SourcePin` + sha | KEEP |

Maturity: about 925 stars, 5 issues total, feature work quiet since 17 July 2026 (dependabot only), export
format moved v1→v2, no API stability promise. Supply chain: pin LiteLLM exactly with hashes (1.82.7/1.82.8 were
compromised in March 2026).

## 3. What is ours (the product core)

1. Per-company collection discovery and schema acceptance.
2. Field-level verified evidence and rejection accounting (`verify_response`, `normalize_quote`) — move to a
   standalone `verify.py` whatever engine extracts.
3. Cross-document matching and merge with per-candidate review state.
4. Multi-value and schedule semantics.
5. Conflicts asked as questions, preview/approved revisions, immutable history.
6. Approved knowledge API/MCP with sources or "Bilmiyorum".
7. File versions that keep approved decisions (D3, planned).
8. Measurement (`docgrain_eval`: golden, stability, support, companies).

## 4. Order of work

1. **Benchmark Docling configurations** on the staged company files (A today's dev; B Docling only — native
   fidelity off, ACCURATE, EasyOCR tr/en, threshold 0.5; C B + Tesseract tur/eng/deu/rus; D C + FULL_PAGE for
   scans/images + picture classification; E D + workspace VLM and picture description for hard pages).
   Measure word recall (PDF text layer; hand references for scans), table cell match, golden questions,
   resolved bbox ratio, chunks per image, time and RAM per page, VLM calls. Rule: if Docling is at most 1 point
   below ours on a metric, our module goes.
2. **bbox tolerance** in `pdf_geometry.normalized_pdf_box`, measured separately.
3. **Removals** in this order once the benchmark agrees: `pdf_fidelity`/`pdf_reading`/`_pdf_missing_tables`;
   DOCX/XLSX native paths (keep number formats); `quality.py`/`_tag_ocr` → confidence report; old Gemini path
   (`gemini_extraction`, `render_pages`, `document_converter()`, `GeminiPageExtractor`, `google-genai`);
   `local_visual_ocr.py` and the proposal part of `selective_vision.py`. ADRs 0018–0020 and 0023 superseded by a
   new ADR. Estimated 1,600–2,000 lines removed.
4. **WP97 rescoped**: keep the reading report (signal from Docling confidence) and hard-page selection/budget/
   resume; transport through Docling `ApiVlmOptions`/`PictureDescriptionApiOptions`. Not merged as is.
5. **Docling Graph A/B** for the `extract` stage only (`--engine docgrain|docling-graph`, runtime template
   from the accepted schema, output always through our verifier). Switch only if accuracy is within 1 point,
   unsupported fields stay 0, stability is equal or better, no conflict is lost, cost ≤ 1.5×.

Unverified, to be settled by the benchmark: page-level selective VLM absence, `page_range`/`parse_charts`
names, VLM retry behaviour, whether Serve returns confidence, the bbox and JPG hypotheses, Tesseract vs EasyOCR
on our documents, runtime templates with `graph_id_fields`, prompt customisation in Docling Graph.
