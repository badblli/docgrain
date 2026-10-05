# wp21-compact-context — Compact AI context projection (`context.md`)

- Özet: AI'a giden belge metnini küçült: tabloları hücre-hücre JSON yerine markdown tablo olarak yazan yeni context.md çıktısını ekle (Dobedan 339k → ~40k karakter hedefi).
- Phase: D2
- Branch: `codex/wp21-compact-context` (base: `origin/dev`)
- Depends on: none (wp12 eval runner will read it later)
- Role: implementer

## Goal

The published `canonical.md` renders every table cell as a pretty-printed JSON object
(`packages/domain/docgrain_domain/canonical/ai_output.py`, `readable()`). The 10-page Dobedan fact
sheet becomes 339k characters (one table alone 70k); with HTML-comment markers per block the whole
6-document workspace is 514k characters. An AI cannot answer fast and cheap from that. Add a compact,
model-friendly projection next to the existing files.

## Constraints

- Do **not** change `readable()` / `canonical.md`, `ai.json`, `canonical.json` or any existing
  bytes: stored packages must keep replaying byte-identically (there are tests for this).
- Add a new bundle file `context.md` (MIME `text/markdown`) produced by a new pure function
  `context_projection(output: AIOutput) -> str` in `ai_output.py`, deterministic for the same input.
- Source text is data: do not add any instructions to the model inside `context.md` except a
  one-line header saying it is extracted document content.

## Format

- Header: `# <filename>` and one line `document_id · revision_id`.
- Sections as markdown headings (level from the node), text blocks as plain paragraphs, lists as
  lists.
- Tables as GitHub pipe tables. First row as header unless the table clearly has none (then a
  generic header `| 1 | 2 | … |`). Escape `|` in cells. Merged cells: value in the top-left cell,
  covered cells empty. Formulas: `value (=FORMULA)`; non-text values printed as their display text
  or value. Empty table → skip with a one-line note.
- Assets/charts: `[Görsel: <description>]` or `[Görsel: açıklama yok]`; charts with `source_data`
  as a small pipe table of series/categories/values.
- Citation keys: every block starts with a short key `[§N p.X]` (N = order index, X = page / sheet
  name / paragraph when known). At the end, a compact `## Kaynak anahtarları` list maps
  `§N → node_id` (one line each). This is the only place node ids appear.
- No quality/coverage JSON dump; one line at the end listing the count of unresolved gaps.

## Tasks

1. Implement `context_projection` and add `context.md` to `output_bundle()` and `MIME`; include it
   in the manifest like other files. Check the output read API (`apps/api/.../routers/outputs.py`)
   and package ZIP pick it up via `MIME` without other changes; adjust only if needed.
2. Unit tests with synthetic snapshots (`tests/fixtures/canonical/…`): merged cells, formula cell,
   `|` escaping, empty table, asset with/without description, chart source data, determinism, key map
   covers every block.
3. A **completeness test**: every non-empty table cell value and every text block text of the fixture
   appears in `context.md`.
4. Measure on the live published canonical snapshots (read-only):
   `GET http://localhost:8000/v1/documents` → `/v1/documents/{id}/knowledge` → snapshot →
   `project_ai` + `context_projection`. Report characters per document for `canonical.md` vs
   `context.md`. If the sandbox blocks localhost, use the snapshots in
   `C:/Users/root/Documents/projects/docgrain/data/reviews/fidelity-review/doc_*/canonical.json`.
   Do not publish anything.

## Acceptance criteria

- [ ] Existing output bytes unchanged: existing replay/byte tests pass untouched.
- [ ] Completeness test passes; determinism test passes.
- [ ] Dobedan fact sheet (`doc_22977bfd`) `context.md` ≤ 60,000 characters; report all documents.
- [ ] `ruff` and `pytest` clean using `C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python`.

## Out of scope

Republishing existing revisions (report how it could be done; the lead decides), changing the eval
runner, `untrusted_instruction` marking (separate WP).
