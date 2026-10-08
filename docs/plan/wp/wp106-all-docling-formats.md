# wp106-all-docling-formats — Accept every file type Docling can read

- Özet: Docling'in okuyabildiği bütün dosya tiplerini (Word/Excel/PowerPoint'in eski ve yeni biçimleri, OpenDocument, HTML, Markdown, CSV, EPUB, e-posta, ses/video, altyazı, özel XML'ler, TIFF/BMP/WEBP görseller…) yüklenebilir ve okunabilir yap; bağımlılığı imajda yoksa anlaşılır bir mesajla reddet.
- Model: derin
- Engine: codex
- Skill: frontend-design
- Phase: D18
- Branch: `codex/wp106-all-docling-formats` (base: `origin/dev`)
- Depends on: WP100, WP104 (merged)
- Role: implementer
- Owner: Jigglypuff (codex)

## Why (user, 2026-10-09)

"Docling'in desteklediği tüm dosya tiplerini destekleyelim." Today we accept 6 formats
(`packages/domain/docgrain_domain/source_format.py`: PDF, DOCX, TXT, XLSX, PNG, JPEG). The worker image runs
Docling 2.130.0, whose `InputFormat` lists 33 formats (lead read it from the image):

DOCX (docx, dotx, docm, dotm), DOC (doc, dot), RTF, PPTX (pptx, potx, ppsx, pptm, potm, ppsm), PPT (ppt, pot,
pps), HTML (html, htm, xhtml), MHTML (mhtml, mht), IMAGE (jpg, jpeg, png, tif, tiff, bmp, webp), PDF, ASCIIDOC
(adoc, asciidoc, asc), MD (md, markdown, txt, text, qmd, rmd), CSV, XLSX (xlsx, xlsm, xltx, xltm), XLS (xls, xlt),
ODT/ODS/ODP (+ templates), XML_USPTO, XML_JATS (xml, nxml), XML_XBRL (xml, xbrl), XML_DOCLANG (dclg), DCLX,
METS_GBS (tar.gz), JSON_DOCLING (json), AUDIO (wav, mp3, m4a, aac, ogg, flac), VIDEO (mp4, avi, mov, mkv, webm),
VTT, LATEX (tex, latex), EMAIL (eml, msg), EPUB, BOXNOTE, IWORK_PAGES (pages), EBCDIC, AFP.

## Goal

1. Derive our accepted formats from Docling's `InputFormat`, `FormatToExtensions` and `FormatToMimeType`
   instead of a hand list (one mapping module in `packages/domain`; keep `SourceFormat` values stable for the
   existing six so stored data stays valid). TXT keeps our own exact-text path (it keeps 100 % of words).
2. Detection and verification: extension + MIME + content sniffing (magic bytes / zip member names / XML root)
   so a renamed file is rejected as today (`FormatMismatch`). Ambiguous XML (USPTO/JATS/XBRL/DocLang) is decided
   by Docling's own format detection.
3. Worker: convert every format through Docling with the default reading profile. Formats whose backend needs an
   optional dependency or model (audio/video ASR, legacy DOC/PPT/XLS if Docling needs LibreOffice, EBCDIC/AFP,
   METS) are checked at startup: if unavailable, the API rejects the upload with a clear Turkish message ("Bu dosya
   türü bu kurulumda henüz açık değil.") instead of failing in the worker. List exactly which dependency each needs;
   the lead adds them to the image.
4. API upload contract and `docgrain ingest-folder` accept the new extensions; folder ingest skips nothing that
   Docling can read and reports unsupported files with the reason.
5. Web: the file picker `accept` list and the Belgeler copy ("PDF, Word, Excel, metin veya görsel") come from the
   same list (Tailwind + shadcn only, no new CSS).
6. Images: TIFF (multi-page), BMP, WEBP follow the image rules (full-page OCR; keep coordinates).
7. Tests with small synthetic samples generated in the tests (no customer files, no large binaries): at least
   PPTX, HTML, Markdown, CSV, ODT, EML, EPUB, TIFF, WEBP, VTT; and the "not enabled" path for audio.

## Rules

Grep Docling's installed source for every format/backend name; do not guess option names. No deletions of our
code: anything replaced stays, marked unused (decision 18 rule). No network in tests.

## Acceptance criteria

- [ ] Upload + parse works for every format whose dependency exists; the rest are rejected up front with the
      Turkish message; nothing reaches the worker and fails silently.
- [ ] Existing six formats unchanged (stored `SourceFormat` values and outputs).
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean, `tsc` 0.
- [ ] Report (Turkish): format table (accepted / needs dependency X / not possible), the image changes the lead must
      make, and the live check commands.
