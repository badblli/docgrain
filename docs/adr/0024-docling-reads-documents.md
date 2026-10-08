# ADR 0024 — Docling reads documents (decision 18)

- Date: 2026-10-08
- Status: implemented; real worker-image acceptance must be rerun by the lead.
- Supersedes the reader/OCR choices in ADRs [0018](0018-image-evidence-local-ocr.md),
  [0019](0019-native-source-structure-fidelity.md) and [0020](0020-local-first-visual-review.md).
  Supersedes ADR [0023](0023-local-cpu-visual-proposals.md) as a general reader direction;
  its optional proposal API and human review contract remain in place.
- Roadmap decision 18 and the WP100 lead benchmark take precedence over older parser decisions.

## Evidence and decision

The lead's 2026-10-08 worker-image comparison covered 64 files from 12 companies.
`C_tesseract` reached 95.7% PDF text-layer word recall against A's 94.8%, eliminated
2,893 unresolved boxes and took 16 minutes against A's 49. No file was more than one
percentage point below A. This is the decision-18 replacement gate, not a new claim
of semantic correctness or automatic approval.

`DocumentParser()` and the live worker now use `C_tesseract`: Docling 2.130.0,
TableFormer ACCURATE with cell matching, Tesseract CLI tur/eng/deu/rus, CPU with two
threads, parsed pages and page images at scale 2. Profile identity version 2,
effective pipeline options, formatter/routing versions, dependency versions and
the option digest enter the processing spec. New conversions use canonical 0.6.0
and mapper/adapter `docling-2`; historical snapshots are not rewritten.

PNG/JPEG and PDFs with no text layer anywhere use `OcrMode.FULL_PAGE`. Digital PDFs
keep `PDF_AWARE_LAYOUT_REGIONS`. Docling 2.130 exposes one OCR mode for a pipeline,
not a per-page mode selector. **Limitation:** a mixed digital/scanned PDF stays in
region mode for all pages; scanned pages in it do not get forced full-page OCR.
The file probe reads only the PDF text layer; it does not reconstruct content.
See the pinned [OCR implementation](https://github.com/docling-project/docling/blob/v2.130.0/docling/models/base_ocr_model.py).

## Removed and retained boundaries

Removed: our PDF table fidelity and reading-order algorithms, missing-table
fallback, native DOCX extraction and OOXML string alignment, native XLSX
completion/chart extraction, the duplicate PDF conversion/rendering and old
whole-page Gemini extractor. `A_current` cannot run after these removals and is
rejected explicitly. B/D/E remain selectable for remeasurement. D/E retain their
whole-file forced OCR configuration, including on digital PDFs, so they are not
the default. E still requires explicit endpoint, model and nonempty key environment
name; default converters disable remote services.

Retained: deterministic TXT, source verification and versioning, canonical
mapping/publication, geometry adapters, original image bytes/EXIF evidence, OCR
origin and literal-cell provenance, measurement and human review. The remaining
XLSX adapter maps **only Docling-emitted cells** to worksheet coordinates and adds
typed values, formulas/stored results and display formatting. It never discovers
omitted cells, extracts chart XML or evaluates formulas. The small formatter
supports ordinary decimal/grouped number, percent and common date/time formats;
unsupported formats keep Docling's display text. General Excel locale, conditional,
currency and custom-format equivalence is not certified.

Docling low/poor grades (`fair`/`poor`) now drive existing `low_text_page` and
`ocr_low_confidence` issue codes. OCR is the flagged component only when its score
is the lowest available Docling page score; layout/parse/table problems remain
general reading gaps. Missing page geometry remains an operational failure.
The old per-cell 0.8 quality threshold and empty-content page heuristics are gone.
Raw confidence reports are retained; grades never approve content. Literal OCR
still carries `ocr_needs_review` independently of quality grades.

The DoclingDocument JSON is a checksum-addressed, immutable object version referenced
by the canonical revision. DOCX evidence uses existing `artifact_object` locators
with JSON object paths, not invented OOXML locations. Standalone mapping without a
storage client retains the JSON in canonical metadata with its content-addressed
URN. JSON object paths are parser references; they do not guarantee stable native
Word block positions when earlier content changes.

The source-review page API keeps its PNG/manifest paths. Images now come from the
same Docling conversion at 144 DPI; the API reads the manifest DPI and preserves
the historical 200-DPI fallback. There is no second render/conversion pass.

Separate selected-artifact review tools (`local_visual_ocr`, `selective_vision`,
optional local CPU proposal API) have not been benchmarked as default readers in
this WP and stay unchanged. `selective_vision.GeminiSelectedExtractor` still imports
`google.genai`, so the dependency remains. Their proposal generation/transport
migration is later work; accepted manual reviews, uncertainty and source links stay.

## Validation and remeasurement

WP98's synthetic corpus remains the offline integration gate. The new default
tests check canonical word recall for DOCX/XLSX/TXT at 100%, percent/date display,
PDF columns/table, image/scanned text, confidence metadata and review page images.
Host tests cover routing, grades, artifact evidence, formatter/formulas and the
absence of native cell completion. Host tests do not certify real Docling inference.

XLSX benchmark recall now compares the source's formatted display to the extracted
display, so `0.15` with `0%` is `15%` on both sides. Typed numeric values are also
checked directly in tests. Historical WP98 raw-value XLSX recall is not directly
comparable to this display-based metric.

With baked model caches, run inside the worker image from `/srv`:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m pytest -q tests/integration/test_docling_profile_conversions.py
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python benchmarks/docling_profiles.py --profiles C_tesseract --root /srv/data/sources --out /srv/data/benchmarks/wp100-c
```

The host venv has no Docling and this worker's Docker API access is denied; real
conversions and PostgreSQL/MinIO/EasyOCR integration acceptance remain unverified
here. No real company documents or model calls were used in WP100 tests.
