# wp123-image-text-headings — Misread logo headings must not split records

- Özet: Sayfa logosundan OCR ile okunmuş anlamsız başlıklar ("MAX yi", "NL,") artık kayıtları ayırmasın; gerçek kat/bölüm başlıkları ayırmaya devam etsin.
- Model: derin
- Engine: codex
- Phase: D21
- Branch: `codex/wp123-image-text-headings` (base: `origin/dev`)
- Depends on: WP114, WP118 (merged)
- Role: implementer
- Owner: Charizard (codex)

## Why (lead live check, 2026-10-18)

WP114's structure-context veto (`structure_context.py` `contexts_conflict` / `_labels` / `structure_vocabulary`,
used by `merge.py` `_match` union and `match.py`) splits records whose structural labels differ. Across documents
it fires when one record sits under a label that the other document's vocabulary also has.

On one live hotel workspace a republish dry-run grows 132 → 143 records. Five identical "Lobby Bar" records
(and "Tennis Bar", "Bowling Bar", … — 12 vetoed pairs) whose matches are all accepted stay apart. Every one of
the 12 vetoes is caused by a single label: the heading "MAX yi". The two concept PDFs (summer, winter) are
born-digital, but every page carries the hotel logo as a raster image; Docling OCRs the logo and labels the
result `section_header`. The canonical snapshot then has headings like "MAX yi", "MAX wer", "MA, Mr", "NL,",
"Аи,", "NN", "Fb" and other garbled logo text next to real headings ("Suite Land", "Food Hall (3)").

The data that separates them is already in the canonical snapshot (from Docling's OCR cells, WP107/WP118):

- real headings on these pages: `annotation.provenance.confidence` is `None`, `producer_id`
  `producer-structural-parser` (native PDF text);
- logo headings: `confidence` measured, `confidence_method` `"<engine>-recognition-min:ocr"` (or `:mixed`),
  `producer_id` `producer-<engine>`, on a page that also has native text nodes.

OCR confidence alone does NOT separate them: in fully scanned documents real headings range from 0.0 to 0.97
(e.g. a scanned menu "YENER | STARTERS" 0.0, a program "e 31 ARALIK SALI…" 0.0) and logo junk reaches 0.84.
The reliable signal is "OCR text on a page that has a native text layer" = text inside a picture.

## Goal

The veto ignores headings that are not document structure; real floor/section differences still veto.

## Tasks

1. `pin_structure` (`packages/records/docgrain_records/structure_context.py`): a section node is an
   **image-text heading** when its provenance is OCR-derived (`confidence_method` ends with `:ocr` or `:mixed`)
   and the same page (evidence locator `page_number`; a document without page numbers counts as one page) has at
   least one node with native text (provenance without `confidence_method`, any kind with text: section,
   text_block, list text, table). Image-text headings are left out of pinned `heading_path`s: descendants get
   the ancestors' path (tree-based, not linear — a sibling heading must not adopt them). Fully scanned pages
   keep their OCR headings. Keep the replaced lines as `KULLANILMIYOR (karar 18, WP123)` comments.
2. Junk titles for the veto (`context_signature`, `_labels`; also used by `structure_vocabulary` and
   `record_contexts`): a heading title or row header with fewer than 2 letters after NFKC (punctuation-only,
   digits-only, "№", "*") is not a structural label. A `section_title` equal to an ignored heading title is
   ignored too. Do not change heading evidence rules or extraction prompts otherwise.
3. Republish (`apps/worker/docgrain_worker/republish.py`): stored `context.md` pins were made by the old
   `pin_structure`. Before matching, refresh them from the canonical snapshot of the **same pinned
   `knowledge_revision_id`** (source.json) via the API `/v1/documents/{id}/knowledge` (as
   `records_pipeline.load_docling_documents` does): strip the old `§N structure=`/`§N table=` footer lines,
   `pin_structure` again, write the refreshed copy under the republish output directory (never overwrite the
   job runtime `records/`), recompute each loaded record's `structure_context` with `identity_context`, and run
   `propose_matches` / `merge_matches` on the copy. A document whose snapshot is missing or of another revision
   keeps its stored pins. Report `"structure_pins_refreshed": <n of m documents>` in the JSON. No model call,
   no extraction; `--dry-run` publishes nothing. Bump `RULES_VERSION` in `auto_accept.py` to `"wp123"` (keep
   the old line as a KULLANILMIYOR comment): the republish output directory and its `merge_state.json`
   identity map are keyed by it, and a stale `wp115` identity map would replay the old splits.
4. Tests (synthetic, no network): (a) snapshot with a born-digital page that has a native heading, a native
   table and an OCR logo heading → logo heading absent from all pinned paths, native heading present;
   (b) fully OCR page with two OCR floor headings ("Alt Kat", "Çatı Katı") and the same room name under each →
   still separate records (veto keeps working); (c) two documents, identical record name, one under an
   image-text heading that the other document also has → merged; (d) punctuation-only/one-letter title ignored
   by `_labels`; (e) republish refresh uses the pinned revision only and leaves runtime files untouched.
   All existing WP114/WP118 structure tests stay green unchanged.

## Acceptance criteria

- [ ] Tests (a)–(e) pass; existing structure-context tests unchanged and green.
- [ ] `.venv/Scripts/python -m pytest -q` green, `ruff check` clean.
- [ ] Lead: live republish `--dry-run` on the affected workspace no longer grows (≤ 132 records), the 12 vetoed
      identical-name pairs merge, and the other workspaces' dry-run counts do not get worse.

## Rules

Never delete replaced code (mark `KULLANILMIYOR (karar 18, WP123)`). No Git. No network in tests. Conflicts are
asked, never guessed. Report in Turkish with the lead's live commands.

## Notes

- Lead's probe numbers (summer concept PDF): 78 section nodes, 29 OCR; winter: 60 / 23.
- Republish: `docker compose exec worker python -m docgrain_worker.republish --workspace <id> --dry-run`
  (workspace ids in `.lead/workspaces.json`, not committed).
