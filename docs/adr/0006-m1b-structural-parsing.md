# ADR 0006 — M1b multi-format structural parsing

Status: implemented foundation; output fidelity remains fixture-measured.

## Decision

M1b is the second half of M1. Official M2 remains selective multimodal enrichment and reconciliation. `DocumentParser` emits a small `StructuralParseResult`; `CanonicalMapper` converts verified structure to canonical knowledge. PDF, DOCX and XLSX use Docling 2.130.0. TXT uses strict UTF-8/BOM decoding and source offsets. Gemini's existing PDF extraction remains a legacy artifact path and is never merged into M1b canonical structure.

Input dispatch checks MIME, extension and PDF/OOXML/TXT bytes. Source bytes and declared SHA-256 are checked before parsing. Canonical persistence requires a non-null MinIO object version ID. Local Compose enables bucket versioning; `SourceVersion.storage_uri` pins the exact `versionId`. Historical unversioned objects are excluded. An isolated source/revision append remains separate from legacy document artifacts and does not publish `canonical.json`.

## Contract version

The original `canonical-knowledge-0.1.0.schema.json` is immutable. M1b adds optional `TableCell.formula`, `cached_value`, `display_text`, `row_span` and `col_span`; because these change the versioned core schema and old validators reject extra fields, new snapshots use **0.2.0** and `canonical-knowledge-0.2.0.schema.json`. Runtime validation accepts historical 0.1.0 snapshots but rejects 0.2.0-only cell fields in a 0.1.0 snapshot. The generated 0.2.0 artifact has a fixed schema-version const. Subsequent core contract changes must create a new schema artifact; no previously released versioned schema file is overwritten.

## Measured behavior and limits

Container probe: Docling 2.130.0 / docling-core 2.99.0 / PyMuPDF 1.28.2. PDF provenance used `BOTTOMLEFT` point boxes; DOCX text/table/picture nodes had empty `prov` and required OOXML block alignment; XLSX had sheet groups and table ranges but omitted an isolated formula cell. The adapter preserves that cell from the workbook and reports `cell_missing_in_docling`. A ruled PDF table missed by Docling is recovered with a narrow PyMuPDF `find_tables()` fallback and reported as `docling_missed_table`. A picture classification without binary is not turned into an `AssetNode`. Scanned/low-text pages remain partial; OCR routing belongs to M2.

Source versioning pins object bytes, but bucket administrators can still remove a version; this is versioned identity, not object-lock retention. Current canonical table initialization remains an additive startup DDL path, not a production migration system. Full production migration, model artifact provisioning and robust worker crash recovery remain separate operational work. Raw structural assets are internal extraction artifacts; canonical artifact publication remains a later milestone.
