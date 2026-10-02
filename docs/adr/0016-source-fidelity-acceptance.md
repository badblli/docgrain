# ADR 0016 — Independent source fidelity checks before enrichment and embeddings

2026-10-02 · implementation / local review.

Problem: canonical-to-output preservation does not prove source-to-canonical fidelity.
Real five-file review matched TXT text, DOCX body paragraphs and XLSX source cells,
but a PDF table duplicates a header prefix and assigns a total to the wrong column
despite high native-text token coverage. Missing
visual descriptions also mix repeated logos with information-bearing floor plans.

Add an explicit offline, source-SHA/size-pinned audit. It reads source bytes with
OOXML/OpenPyXL/PyMuPDF independently of Docling table mapping, checks TXT/body
paragraphs/spreadsheet cells, and reports page-local native PDF token occurrence
coverage only as a diagnostic. Version-pinned manually reviewed golden table-cell
assertions detect semantic column assignment errors that token metrics cannot.
Unknown/unassessed aspects remain named; never turn token recall into semantic success.

Audit is a local review artifact, not a canonical mutation or automatic acceptance
state. Original snapshots, historical output packages and ingestion jobs remain
immutable/unchanged. Visual triage is a reviewer input keyed by artifact hash,
source revision and node/evidence; it does not automatically clear visual gaps.
Prioritize floor plans and table/header conflicts for selective Vision. Logos,
photos, visible text and inferred descriptions must remain distinguishable.

No new runtime framework/provider dependency. Existing optional worker dependencies
support the offline CLI. Negative contracts include source checksum mismatch and
misassigned table cells even when all source words survive. Real source documents
and review labels remain ignored local data; synthetic contract tests are committed.
External model execution uses an explicitly selected provider; this audit itself
does not make model calls, write canonical revisions or generate embeddings.

Selected provider proposals pin source bytes, revision, node, evidence and exact
asset/render hash before a call. JSON validation establishes only output structure.
The actual selected Gemini table response corrected three cells but added a letter
absent from the source to another header. Reconciliation therefore compares each
changed cell with independently reviewed golden assertions: source-checked changes
enter a separate table preview, conflicting proposals are rejected, and unassessed
changes remain pending. A shape change requires separate structural review.

Preview rows and visual descriptions are review artifacts, not authoritative
snapshots. Applying accepted fields requires a new processing/review revision with
producer/field evidence and CAS, followed by new immutable output publication.
Do not rewrite a historical snapshot or mark a proposed description as complete.
