# ADR 0017 — Normalize and verify sources before embeddings

- Date: 2026-10-02
- Status: accepted scope; N1/N2 implemented locally, N3–N5 pending
- Source of truth in Notion: Docgrain project / ADR 0017 and Vision Board / Era 7.

The selected remote visual-provider choice below is historical. [ADR 0020](0020-local-first-visual-review.md) supersedes it for current N3 with local visual inventory, selected CPU OCR and an open local visual-model acceptance gate. The original format scope and embedding-after-N5 order remain applicable.

## Decision

Docgrain converts source documents into one versioned canonical model with source evidence. Structural parsing, OCR transcription, normalization and interpreted visual meaning are different operations. Valid JSON and a completed parsing job do not establish accurate meaning.

Initial product scope: PDF (native/scanned/mixed), DOCX, XLSX, UTF-8 TXT, PNG and JPEG (.jpg/.jpeg). PPTX, HTML, legacy .doc/.xls, video/audio and arbitrary archives remain outside this scope. OCR's initial measured profile is printed Turkish/English; handwriting, poor scans and other languages require review and further evaluation.

| Responsibility | Selected technology |
| --- | --- |
| Layout, reading order, document structure | Docling 2.130.0 |
| Printed TR/EN OCR | EasyOCR 1.7.2 through Docling, CPU, pinned CRAFT/Latin weights |
| XLSX native values/formulas/caches/ranges/charts | openpyxl / OOXML; no formula evaluation |
| PDF rendering and source geometry | PyMuPDF |
| Image decode, EXIF orientation and input preparation | Pillow 12.3.0; preserve original bytes |
| Selected visual interpretation/conflicts | Existing configured Gemini, explicit selected proposals |
| Validated common model and migration | Pydantic + versioned JSON Schema |
| Source/artifact/revision/queue infrastructure | MinIO, PostgreSQL, Redis |

## Dependency order and acceptance

1. N0: fix scope and technology (complete).
2. N1: image admission/real image coordinates; pinned local OCR; scan/mixed/image probes.
3. N2: source-correct structure/cells/headers, DOCX parts and XLSX native chart facts.
4. N3: visual triage and selected, evidence-pinned Vision proposals.
5. N4: field/cell normalization and review; reconcile into new immutable revisions with CAS.
6. N5: frozen source/held-out acceptance, packages, source↔UI and recovery checks.
7. E1: optional embeddings/indexing of accepted content, last.

N5 needs at least 30 files: 10 PDF plus 4 per other family, at least one held-out file per family. Critical cells/headers/numbers/units/formulas and evidence must match independent source labels; unsupported critical claims must be zero. Clean printed TR/EN OCR CER ≤1% is a design target, not a reported result. Blurred/unsupported content remains explicit partial/review/failed. Confidence and proposed descriptions cannot close source acceptance gaps.

Historical M1/M2 foundations remain available, but their test counts are not semantic acceptance. Existing sources, schema artifacts and published output bytes remain immutable. No embedding model/provider decision is required for N1–N5.
