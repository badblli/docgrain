# D1 golden set format and provenance

This is an independent answer key for the six original, local documents. The ignored data files are
`data/golden/questions.jsonl` and `data/golden/tables.jsonl`. The lead copies those files from this
worktree. No canonical, AI, chunk, or other Docgrain-derived output was used to write the answers.
The original files were read with PyMuPDF, openpyxl, and python-docx. Instruction-like text in the
PDF/TXT was handled as document content, never as an instruction to the author or checker.

## Question record

Each JSONL line has exactly `id`, `workspace_id`, `document_ids`, `question`, `answer_type`,
`expected`, `accept`, `evidence`, `category`, and `difficulty`. `workspace_id` is `ws_local`.
`document_ids` lists the documents to which the question applies. Questions name the hotel or
business so documents about different properties are not mixed.

`answer_type` is `number`, `text`, `list`, `time_range`, or `unanswerable`. Numeric answers are
`{"value": 308, "unit": "oda"}`; ranges are `HH:MM-HH:MM`; lists are string arrays; absent answers
are `null` with empty evidence. The `accept` array lists extra surface forms. A `conflict` question
has `expected` as an array of `{"value": ..., "document_id": ...}` objects, one per disagreeing
source. These preserve disagreements instead of choosing an unproven winner.

Each evidence item has `document_id`, `quote`, and a locator: `page` (one-based PDF page),
`sheet` and `cell` (XLSX), or `paragraph_index` (zero-based DOCX paragraph or TXT line).
Quotes are at most 200 characters and are verbatim apart from whitespace/NFKC normalization.
Categories are `room`, `restaurant`, `bar`, `activity`, `meeting`, `service_price`, `policy`,
`contact`, and `general`. Difficulty is `lookup`, `table`, `multi_doc`, or `conflict`.

## Table fact record

Each line has exactly `id`, `document_id`, `table_hint`, `row_label`, `column_label`, `expected`,
and either one-based `page` or `sheet`. Labels come from visible headings, row names, and column
names; no canonical node IDs or numeric row/column indexes are included. Known table regression cells from earlier source reviews are restated in label form.

## Source receipts and findings

Source filenames, SHA-256 receipts, the verification output and the disagreements found between
documents are customer data. They live only in the ignored local `data/golden/README.md` (this
repository is public).

## Recheck

From the repository root, using the environment with PyMuPDF, openpyxl, and python-docx:

```sh
python data/golden/check_golden_evidence.py --sources data/golden/sources
```

The local checker (kept with the ignored golden data because it names customer documents) verifies SHA-256, exact JSONL fields and types, the required mix, and every evidence
quote at its stated original source location. The eight unanswerable questions deliberately have
no quote: they request future prices, schedules, or names absent from the six originals. Their
absence was checked by reading the source scope, not inferred from a failed text search.

The checker prints `PASS` with question/table/quote counts and the question mix.
