# wp11-golden-set — Golden questions and table facts from the six live documents

- Özet: altı belgenin orijinalinden 60+ soru ve 40+ tablo hücresinden oluşan cevap anahtarını hazırla (Docgrain çıktısına bakmadan).
- Phase: D1
- Branch: `codex/wp11-golden-set` (base: `origin/codex/wp00-team-harness`)
- Depends on: wp00
- Role: implementer

## Goal

An independent answer key, written from the **original sources** (not from Docgrain output), so we
can measure whether normalization and AI answers are correct. Without it nothing in D2–D6 can be
accepted.

## Inputs (local, Git-ignored)

The six live documents (`GET http://localhost:8000/v1/documents`):

| Document | File |
| --- | --- |
| doc_f3850507 | doobedan_full.pdf (24 pages) |
| doc_22977bfd | Dobedan Exclusive Hotel & Spa Fact Sheet 2025 YAZ -TR.pdf (10 pages) |
| doc_237edd14 | TR_Corendon Playa Kemer Fact Sheet - 2026 - SUMMER.pdf (7 pages) |
| doc_09ab90f4 | FB GÜNCEL AÇILIŞ KAPANIŞ SAATLER 2025.xlsx |
| doc_0f906728 | Misafir İlişkileri Sıkça Sorulan Sorular Exclusive).docx |
| doc_2a54df6f | dobedan_exc_custom_talimatlar.txt |

Originals are already downloaded by the lead (read-only for you):
`C:/Users/root/Documents/projects/docgrain/data/golden/sources/<document_id>.<ext>` with
`manifest.json` (filename, SHA-256, size, revision). Use the Python at
`C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python` (has pymupdf, openpyxl,
python-docx). Write your outputs to `data/golden/` **inside your own worktree**; the lead copies them.

**Read sources with PyMuPDF/openpyxl/python-docx or by viewing rendered pages. Do not read
`canonical.json`, `ai.json`, chunks or any Docgrain output while writing answers.** The key must not
inherit parser mistakes. The user approved cloud processing of these documents for measurement.

## Deliverables

1. No package code: wp12 (in parallel) owns `packages/evaluation/` including the golden models.
   Keep exactly the field names below; they are the contract between the two WPs.
2. `data/golden/questions.jsonl` (ignored), ≥ 60 questions:
   - `id`, `workspace_id`, `document_ids` (which docs may contain the answer), `question` (Turkish,
     how a guest would ask), `answer_type` (`number` | `text` | `list` | `time_range` | `unanswerable`),
     `expected` (canonical value: numbers as numbers with `unit`, lists as arrays, times `HH:MM`),
     `accept` (extra accepted surface forms), `evidence` (list of `{document_id, page|sheet!cell|paragraph_index, quote}`
     with the exact source text ≤ 200 chars), `category` (`room`, `restaurant`, `bar`, `activity`,
     `meeting`, `service_price`, `policy`, `contact`, `general`), `difficulty` (`lookup` | `table` |
     `multi_doc` | `conflict`).
   - Mix: ≥ 10 table-cell questions, ≥ 8 cross-document, ≥ 8 unanswerable (plausible but absent,
     e.g. a price for a year that is not in the documents), ≥ 4 where two documents disagree
     (`expected` lists both values with sources; note the conflict).
   - Cover every document; ≥ 20 from doobedan_full.pdf (its tables are the known weak spot).
3. `data/golden/tables.jsonl` (ignored): ≥ 40 parser-independent table facts:
   `{id, document_id, page|sheet, table_hint (nearby heading text), row_label, column_label, expected}`.
   Use labels, not node ids or row/column indexes, so facts survive re-parsing. Include the six
   known Dobedan page-2 cells (`data/reviews/fidelity-review/doc_22977bfd/golden.json`, restated in
   label form) and ≥ 15 cells from doobedan_full.pdf markdown-style tables.
4. `data/golden/README.md` (ignored copy) and a committed `docs/plan/golden-format.md` describing
   the format, how answers were written and SHA-256 of each source used.

## Acceptance criteria

- [ ] Both files are valid JSONL with exactly the fields above (checked by the evidence script).
- [ ] Counts and mixes above met (report a table of counts).
- [ ] Every `evidence.quote` occurs verbatim (after whitespace/NFKC normalization) in the source
      text you extracted — include a script `docs/examples/check_golden_evidence.py` and its output.
- [ ] Report lists any question where you were unsure, and every conflict you found between documents.

## Out of scope

Running any model, changing Docgrain outputs, writing the eval runner (wp12).
