# N1 — Image inputs and source-pinned local OCR

## Implemented

- Six admitted formats: PDF, DOCX, TXT, XLSX, PNG, JPEG. `.jpg` and `.jpeg` share JPEG; extension/MIME/signature and full image decode must agree. Corrupt images return 422; format mismatch/animated images return 415.
- EasyOCR 1.7.2 TR/EN CPU through Docling 2.130.0, CRAFT/Latin SHA-256s pinned in `docgrain_worker/ocr.py`. Checkpoints are built into the worker; runtime never downloads OCR weights. Docling layout/table weights have the existing Docling acquisition behavior; the offline claim applies specifically to OCR checkpoints.
- Original bytes retained, EXIF 1–8 reversible geometry, source/input hashes and dimensions. Canonical image evidence has original-pixel boxes, not invented PDF pages. Browser overlays apply EXIF orientation to the source bbox.
- Native PDF text wins overlapping OCR; literal OCR and mixed native/OCR blocks retain producer, confidence method and unreviewed state. All OCR requests source review, including high scores. Low scores and no text are explicit gaps.
- Canonical 0.5.0 / AI document 1.1.0 for the new processing profile. Historical schema/output parity is tested. JSON/ZIP contain the original source-image asset. Legacy PDF export reuses the same conversion.

## Source probes and limits

Frozen synthetic pixels: `tests/fixtures/structural/printed-tr-en.png` (rendered locally, no external document). Independent literal labels:

```text
ODA SAYISI 127
Room area 42 m2
Türkçe: ç ş ğ ü ö İ ı
```

The source is exercised as PNG, EXIF-6 JPEG, image-only PDF, mixed PDF and PDF with an overlapping native text layer. Tests require each source label once, exact native text preservation and source-backed unreviewed OCR provenance. A blank image is a negative case; all eight EXIF transforms are checked against real asymmetric pixel content. This small probe is not the frozen 30-file/held-out N5 evaluation and does not establish the overall ≤1% CER target.

Existing five real source snapshots/packages are compared against pre-N1 file checksums. They are not reprocessed or rewritten. Their known table/visual errors remain open for N2–N4.

Executed on 2026-10-02: full worker/PostgreSQL/versioned MinIO/Docling/EasyOCR suite **247 passed, 0 skipped**; host **180 passed, 67 runtime/service tests skipped**. Ruff and production web build (including TypeScript checks), API/web/worker Docker image builds and Compose configuration passed. Each of the five existing snapshots regenerates the same six output-file SHA-256s as before N1.

Local deployment GET checks also confirm all five heads/snapshots and all 30 stored output-file checksums unchanged. Browser smoke verifies the live document list/output and six-format admission text. A separate browser fixture uses real OCR output over synthetic EXIF-6 JPEG (read responses intercepted, no live records written): original 500×1500 pixels display as 1500×500; the OCR bbox overlays the correct source line, Turkish text and OCR review/low-score gaps render. A pre-existing missing favicon returns 404; no application console error was found in the fixture review.

## Run

```sh
docker compose build worker api web
# Canonical local OCR review: keep the worker GEMINI_API_KEY blank.
docker compose up -d
```

Upload PNG/JPEG or a scanned/mixed PDF; open **AI çıktısı**. OCR text is labeled as unverified, **Eksikler** distinguishes OCR review/low confidence/no text, and source evidence opens the original image or PDF page with bbox. Photo/plan meaning needs selected Vision and source review; OCR alone does not supply it.

Host tests skip runtime/service gates. Full real tests run inside the worker with `DOCGRAIN_M1_TEST_DATABASE_URL` and `DOCGRAIN_M2G_TEST_S3`, using unique schemas/buckets and explicit blank Gemini. No live embedding call is part of N1.
