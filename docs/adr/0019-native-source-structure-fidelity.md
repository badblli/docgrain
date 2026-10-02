# ADR 0019 — Native source structure and cell evidence

- Date: 2026-10-02
- Status: N2 local implementation; broad source acceptance remains N5.

## Decision

Keep Docling 2.130.0 as the layout/parser capability. Native OOXML owns Word literal parts and Excel cell/chart facts. PyMuPDF native words and ruled geometry independently check PDF table assignments. A successful parser job does not certify source meaning.

N2 is opt-in for library callers (`DocumentParser(native_fidelity=True)`) and enabled in the worker by `DOCGRAIN_NATIVE_FIDELITY_ENABLED=true`. Processing adapter/mapper `n2-1` and its source strategy enter the processing digest. Historical modes remain callable and historical packages stay unchanged.

### PDF

- Use `find_tables(strategy="lines_strict")`; filled text backgrounds must not become columns.
- Run native table detection in an in-memory unrotated view. Record native crop coordinates separately from Docling's visible-page frame; map both to the actual rotated render. Source bytes are never edited.
- Match table regions and shape before replacing cells. Shape conflicts, mixed OCR/native cells and ambiguous assignments remain review gaps. Ruled recovery has cell evidence. Borderless/irregular/raster tables retain Docling/OCR plus explicit unresolved conflicts; no universal table accuracy claim.
- Assign wholly contained native words to physical cells. Preserve boundary words and the previous parser text for review. This fixes generic column assignment errors; there is no document-ID or hotel-specific patch. Changes are unreviewed, never approved automatically.
- Split accidentally joined native columns only when source blocks and parser blocks have exact token multiset parity. Store both representations. Geometry XY cuts establish a candidate order in native source orientation. Ambiguous blocks remain explicit; this heuristic is not proof of general reading order.

### DOCX

Walk actual OOXML paths instead of matching strings. Preserve repeated paragraphs, tabs/line breaks, heading/list references, table cells/gridSpan/vMerge, referenced header/footer/note parts, inline/floating image relationships and original media bytes. Part order is body followed by referenced parts, not rendered page order; do not invent pages. Field results are stored literals, not evaluated. Missing parts, tracked changes, embedded charts and unsupported content create issues. Full Word layout/shape/style equivalence is outside the measured N2 probe.

### XLSX

Pin openpyxl 3.1.5 and python-docx 1.2.0. Preserve typed value, original formula, stored result, number format, merged range and covered-cell facts. No formula evaluation or invented display formatting. Read native chart XML, titles/axes/series, category/value/x/y/bubble references, literal/stored points and local cells with their coordinates/types/formulas/formats. Retain stored chart caches separately from current workbook cell facts; caches do not establish freshness. External/missing/oversized references remain gaps; range resolution is bounded to 10,000 cells. Unsupported rendering/visual meaning remains unverified even when native series exist.

## Contract migration

Canonical 0.6.0 adds optional `TableCell.source_attributes` and `ChartNode.source_data`. Native chart source_data is a JSON record with format `docgrain.native-chart`, version 1.0.0, package parts, title, types, axes and per-series literal/cache/reference/cell facts. Chart range evidence uses existing `field_annotations`. Attributes are raw source diagnostics, not approved entity fields or normalized interpretations.

AI document 1.2.0 carries these records unchanged. New fields are omitted when absent; historical canonical 0.2–0.5 and AI 1.0/1.1 schema generation strips the new fields and preserves frozen bytes. Historical snapshots reject these facts under older versions. Producer records distinguish Docling, EasyOCR, native OOXML and native PDF geometry.

No existing head/package is overwritten. N4 performs reviewed reconciliation with immutable revision/CAS; N5 independently accepts the larger corpus. Embedding follows N5.

## Primary references

- [PyMuPDF Page coordinates and table detection](https://pymupdf.readthedocs.io/en/latest/page.html): rotation/frame handling and strict line strategy; behavior verified against installed 1.28.2.
- [openpyxl chart references](https://openpyxl.readthedocs.io/en/stable/charts/introduction.html): native chart source ranges; installed version is pinned to 3.1.5.
