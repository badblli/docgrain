# ADR 0015 — One pre-embedding document output with explicit fidelity gaps

2026-10-01 · accepted for local implementation; user source-fidelity acceptance remains open.

User wants local Inspector + M2 integration and automatic, reviewable output before embeddings.
Supported inputs remain PDF/DOCX/TXT/XLSX. A single format means a validated consumer contract;
it does not guarantee lossless semantic understanding of all possible files.

Canonical PostgreSQL revisions remain authoritative and immutable. A derived `ai.json` 1.0.0
envelope preserves reading-order typed nodes, exact table cell JSON/formula/cache/span facts,
entities/relations/records, source/producer metadata and evidence. Visual assets are references
to verified binary attachments, not invented captions. Explicit gaps include undescribed visuals,
parser issues, empty/failed extraction and formula cells without cached values. Never call
structural completeness semantic completeness; source-to-parser quality is distinct from
canonical-to-output preservation.

Write-time worker publication produces `canonical.json`, `ai.json`, `canonical.md`,
`chunks.jsonl`, JSON Schema and checksum manifest. Immutable versioned storage refs are published
in PostgreSQL only after all bytes are verified; no half-visible output set. Idempotent replay
verifies checksums, preserves source/canonical histories and refuses conflicting output version.
Read API returns only stored/version-addressed outputs; it never parses/derives online.
Empty chunk sets remain publishable with explicit omissions; no synthetic embedding is generated.

UI starts on AI output with readable content, exact tables, image previews, source evidence,
explicit gaps and JSON/download. Engineering Inspector stays available. Existing canonical
revisions can be explicitly backfilled without re-ingestion or a paid model; newly uploaded
verified files publish outputs automatically. Acceptance uses real five-document corpus and
real four-format worker ingestion in isolated storage/schema plus scanned/unsupported negatives.
No embeddings, indexing provider, visual model or universal semantic guarantee in this phase.

References: existing canonical contracts and M2c/M2e projections; Docling parser boundary and
issue/coverage capture (ADR 0006), canonical chunk preservation tests (ADR 0009). No new parser
or framework dependency. Public consumer contract schema is generated from the domain model.

Executed gate: 208 real worker/PostgreSQL/versioned MinIO/Docling tests passed, including
four formats, image-only PDF negative, publication failure/replay, immutable pinned reads,
JSONB key-order stability and ZIP byte fidelity. Five existing user sources and canonical
hash/heads preserved. All five share consumer schema 1.0.0; 23 visual nodes across two PDFs
remain undescribed, explicitly reported. See `docs/PRE_EMBEDDING_OUTPUT.md` for API and review.
