# ADR 0018 — Original image coordinates and pinned local OCR

- Date: 2026-10-02
- Status: implemented; see [N1 verification](../N1_IMAGE_OCR.md).
- Follows [normalization-first scope](0017-normalization-first-scope.md).

## Contract and compatibility

Canonical 0.5.0 adds `image_region` evidence: original encoded `width_px`, `height_px`, EXIF orientation 1–8 and a top-left normalized bbox in the original pixel frame. It is not a PDF page. OCR receives an EXIF-transposed RGB PNG, with white behind transparency. Source and input hashes, dimensions and the reversible preparation version are recorded separately. The original PNG/JPEG is an immutable binary asset in the package.

Processing specs and producers include the effective OCR configuration, runtime dependency versions and CRAFT/Latin SHA-256s. New OCR/image processing uses canonical 0.5.0 and AI document 1.1.0. Stored historical canonical 0.1–0.4 and AI 1.0 remain unchanged: old schema generation prunes the new locator; new locator use under historical versions is rejected. Projection strategy version follows AI document version; the existing package manifest/publication envelope stays 1.0.0.

## OCR routing and provenance

Docling's PDF-aware layout OCR mode uses native PDF cells first, removes overlapping OCR candidates and recognizes uncovered regions. Full-page forced OCR is not used for native PDFs. Parsed pages are retained to identify `from_ocr` cells and raw recognition scores. Native, OCR and mixed blocks are distinguished by producer and `confidence_method`; table cells receive source bbox evidence when available. Raw OCR transcription and location remain in source extraction metadata.

All OCR text remains unreviewed and raises `ocr_needs_review`; scores below 0.8 additionally raise `ocr_low_confidence`. Literal low-score text is retained rather than silently dropped. Recognition scores are not calibrated truth probabilities. Empty/undetected text remains explicit, with original binary available for visual review. No OCR transcription is automatically semantically accepted or described as an interpreted diagram/plan.

The worker defaults to local OCR (`DOCGRAIN_OCR_ENABLED=true`). OCR checkpoints are downloaded and verified at image build time; runtime checkpoint downloads are disabled and missing/tampered checkpoints fail explicitly. Library-level `DocumentParser()` defaults to historical OCR-disabled behavior for reproducible older fixture paths; the live worker opts into the new profile. Legacy PDF artifacts reuse the OCR conversion instead of running another OCR-disabled conversion. Legacy whole-page Gemini remains a separate existing path; local review overrides its worker key to blank. Selected Gemini execution is unchanged.

## Remaining work

N1 establishes an ingestion/evidence/OCR path, not complete source understanding. N2 must address source table-column errors, broader DOCX/XLSX fidelity and native charts. N3–N5 add visual interpretation, review-aware reconciliation and independent corpus acceptance. OCR orientation beyond source EXIF/PDF geometry, deskew, handwriting and degraded scans are not certified by these clean printed probes.
