# D4 held-out Record measurement

`docgrain_eval.record_golden` measures saved Records offline. It never imports an API or model
client, tunes extraction, or changes ReviewState. Source documents and all real annotations,
questions, manifests and detailed results belong only in an ignored local directory such as
`data/golden/` or `.lead/record-quality/`.
Do not put customer names, filenames, hashes or facts in this document or public reports.

## Independent preparation

1. Obtain the lead's explicit source-file list and Document/SourceVersion ids. Read only these
   files; do not enumerate subdirectories or enter `sonDB/` or `yeni db/`. Hash originals in place.
2. From originals, select entire held-out sections before opening saved predictions. Read PDF
   pages visually when tables/layout affect meaning. Build `manifest.draft.json` below. Section
   text is a manual transcription or extraction from originals, never canonical/model output.
   Quotes are exact after NFKC and whitespace normalization; capitalization is preserved.
3. Review previous golden keys, record their SHA-256 receipts and overlap as document/locator/quote.
   No previous key available is a coverage limitation; say so in `overlap_review_note` and
   `coverage_gaps`. Overlapping sections must be excluded before freezing; any marked overlap
   left in holdout blocks the readiness gate. This records declared overlap, not an automatic
   detector for undisclosed prior keys. The lead must review the independence claim.
4. Run `freeze`. It checks original file hashes, refuses forbidden source directories, timestamps
   the section selection and refuses to overwrite a frozen file. Preserve the manifest hash in
   a separate local review receipt. Do not rewrite the frozen file to improve a score. A section
   transcription's faithfulness still requires human review; a source hash alone cannot prove it.
5. Annotate at least 100 meaningful record/field pairs from originals, all available collections
   and source languages. Review tables, units, negative/zero values, explicitly missing fields
   and cross-document conflicts. Select primary English **per field** where an English source
   exists. Preserve supported TR/DE/RU/etc. values and quotes under `i18n`. A missing English value
   can use an evidenced fallback with its actual language. Do not translate facts artificially.
   Use independent stable record ids; record any subsequent explicit identity mapping locally.
6. Write at least 40 source-answerable or explicitly unanswerable questions, including at least
   eight unanswerable. For absence, review the full stated source scope and give a reason; a failed
   search is insufficient. Store expected answers and references to the annotated fields. These
   prepare D5 inputs; this command does not measure question answering or call two models.
7. Only after annotating, inspect predictions. Keep the original key fixed. A source/annotation
   correction requires a new version and written reason; never replace an answer with a prediction.

## Local contracts

All models reject unknown keys. The neutral examples below are illustrative, not a real golden.
Use `model_json_schema()` on `Manifest`, `GoldenField`, `GoldenQuestion` for complete schemas.

`manifest.draft.json` is one JSON object. `frozen_at` is initially null; `freeze` sets an aware UTC
timestamp. Original paths can be absolute or relative to the draft manifest directory. Each
source's Document and immutable SourceVersion ids are required; pin KnowledgeRevision when known.
`available_collections` uses the WP41 names: `property`, `room_type`, `outlet`, `activity`, `facility`,
`policy`, `contact`, `service_price`. Collections that lack source coverage must be stated in gaps.
Meeting rooms are not a separate WP41 collection; document any schema/source limitation explicitly.

```json
{
  "schema_version": "1.0",
  "approved_by": "local reviewer",
  "frozen_at": null,
  "sources": [{
    "document_id": "d_sample",
    "source_version_id": "sv_sample",
    "knowledge_revision_id": null,
    "path": "originals/sample.txt",
    "sha256": "replace with the original file SHA-256",
    "languages": ["en"],
    "sections": [{
      "locator": "page:1/cell:B2",
      "languages": ["en"], "kind": "table", "split": "holdout",
      "text": "Standard room: 32 m²."
    }]
  }],
  "prior_golden_sha256": [],
  "overlap": [],
  "overlap_review_note": "Describe which prior keys were inspected and the overlap search.",
  "coverage_gaps": [],
  "available_collections": ["room_type"]
}
```

`fields.jsonl` has one `GoldenField` per meaningful field, not one entry per translation or quote:

```json
{"id":"f001","record_id":"room_standard","collection":"room_type","field":"size_m2","primary":{"value":32,"lang":"en","evidence":[{"document_id":"d_sample","locator":"page:1/cell:B2","quote":"32 m²"}],"accept":[]},"i18n":{},"absent":false,"conflicts":[],"tags":["table","unit"],"checked_by":"local reviewer","checked_at":"2026-10-05T12:00:00+00:00"}
```

Use `absent:true, primary:null` for a checked missing field; `i18n` and `conflicts` must be empty.
Use literal `false`, `0`, an empty array, or an evidenced phrase for a stated negative value.
Do not treat falsy values as absence. Each present primary/i18n/conflict value carries exact
Evidence. `accept` forms must be decided independently before inspecting predictions. Text uses
the D1 scorer's Turkish-aware case and range normalization; numeric values and common units use
its number/unit parsing. Time ranges normalize `24:00` and punctuation. Lists split stated
`ve`/`veya` alternatives and report matched/expected item coverage; extra list items need human
review. No model or semantic judge is used. Typed numeric fields (`size_m2`, amount etc.) use WP41
units; separate currency/unit fields are scored too.

Conflicts contain at least two expected candidates (value/lang/Evidence). Goldens preserve both
source facts, not a preferred unproven winner. `tags` are `table`, `unit`, `negative`, `missing`,
`cross_document_conflict`; reviewers are responsible for whether these descriptions are truthful.

`questions.jsonl` has expected answers, `field_ids` resolving to golden ids, and reviewed source scope:

```json
{"id":"q001","question":"Standart odanın alanı kaç metrekare?","answerable":true,"field_ids":["f001"],"expected":32,"evidence":[{"document_id":"d_sample","locator":"page:1/cell:B2","quote":"32 m²"}],"document_ids":["d_sample"],"absence_reason":null,"checked_by":"local reviewer","checked_at":"2026-10-05T12:00:00+00:00"}
{"id":"q002","question":"Gelecek yılın oda fiyatı nedir?","answerable":false,"field_ids":[],"expected":null,"evidence":[],"document_ids":["d_sample"],"absence_reason":"The reviewed source specifies size only and contains no future-year price.","checked_by":"local reviewer","checked_at":"2026-10-05T12:00:00+00:00"}
```

Every answerable question's Evidence must support its referenced golden fields. Expected answer
meaning and absence require human checking; the validator does not infer answers from quotes.
Every annotation carries reviewer/date; checking must occur after the holdout freeze. Those
timestamps and reviewer names are declarations, not a substitute for the lead's human review.

## Saved Record inputs and dependency boundary

Accepts WP41 `records.json` envelopes or JSON lists of flattened Records:
`id`, `type`, field objects `{value,lang,evidence}`, `i18n:{lang:{field:value_object}}`.
Null optional fields are absent. An explicit offline adapter may instead use `fields:{field:...}`.
The scorer aligns Records by document, collection and primary/i18n name using D1 Turkish-aware
normalization. It first prefers exact names, then requires a shared meaningful token for a fuzzy
candidate; tied best candidates are reported with their ids. Matched ids are recorded in the
local result. Duplicate saved ids fail. This matching does not merge facts across documents.

For conflict measurement the offline input contract is
`conflicts:{field:{review_state:"needs_review",candidates:[value_object,...]}}`.
Candidate order does not matter; each expected candidate requires matching language, value and
a quotation found in its named source. Silently accepted or missing candidates fail.
The current WP45 base contains WP41 and no WP42 merger. This adapter contract is **not a claim of
compatibility with WP42**; the lead must review WP42's final serialized shape, source version pins
and identity mapping before measuring merged output. WP45 makes no extractor/merge edits.
Freeze originals and annotate before opening predictions even when an adapter will be needed.

## Commands (PowerShell, from the worktree root)

Use the existing repository venv; no installation or network is required:

```powershell
$evalPython = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
$env:PYTHONPATH = Join-Path (Get-Location) 'packages/evaluation'
& $evalPython -m docgrain_eval.record_golden freeze --manifest .lead/record-quality/manifest.draft.json --out .lead/record-quality/manifest.frozen.json
& $evalPython -m docgrain_eval.record_golden validate --manifest .lead/record-quality/manifest.frozen.json --golden .lead/record-quality/fields.jsonl --questions .lead/record-quality/questions.jsonl
& $evalPython -m docgrain_eval.record_golden score --manifest .lead/record-quality/manifest.frozen.json --golden .lead/record-quality/fields.jsonl --questions .lead/record-quality/questions.jsonl --records .lead/record-quality/saved-records.json --out .lead/record-quality/results/run-001
```

Multiple artifacts can follow `--records`. Optional `--context d_sample=path/to/context.md`
allows quote verification against a saved compact context for that same manifest document; its
SHA-256 is reported. Every validation/scoring run
rechecks original file hashes. Output directories must be new; earlier failures stay intact.
Exit code 0: measured thresholds and coverage gates met; 2: thresholds/coverage unmet; 1: invalid
inputs or I/O failure. Neither exit 0 nor `criteria_met:true` changes product acceptance or records.
The tech lead reviews evidence, independence and coverage before D4 acceptance.

`summary.json` records SHA-256 of manifest, fields, questions and every saved prediction file,
coverage gaps, field denominators, and per-collection failures. `fields.jsonl` has one outcome per
golden field with actionable reasons, list coverage and wrong-value examples; `extras.json`
identifies out-of-key slots/conflicts for separate local review.
`summary.md` provides counts without values/quotes. Keep **all** outputs ignored: even ids and gap
notes can contain customer details. Console output omits input values, quotes and free-text gaps.

## Metrics and limits

- Field correctness = entirely correct expected fields / **all expected fields**, including omitted
  fields and checked absences. A present field is correct only when primary, expected translations,
  and conflicts all match; one record/field counts once. Omissions are reported per collection.
- Slot precision = correct evidenced primary/i18n predictions / present **annotated** predicted slots.
  Slot recall = those correct slots / all expected present primary/i18n slots. Conflicts are checked
  separately and do not inflate the precision numerator. These slot metrics have different
  denominators from field correctness; both denominators are reported.
- Unsupported annotated slots have a wrong value/language or missing/invalid Evidence. Predictions
  absent from the frozen key are `out_of_key_slots`, excluded from both supported and unsupported
  counts. Review them separately without extending the key from predictions. Explicitly annotated
  absences count as unsupported if a prediction fills them.
- Every predicted quote must occur after normalization in the named original document (or its
  supplied `context.md`). Its locator is retained in output but differences between compact keys
  and original page/line notation do not fail Evidence. `evidence_unknown_document` and
  `evidence_quote_not_in_source` accompany `invalid_evidence`. Source text remains data only.
- For lists, `list_items_matched/list_items_expected` and a coverage ratio describe partial recall.
  Missing list fields contribute their expected items to the denominator. Correctness requires
  every expected item; extra predicted items are outside this key's item-level judgment.
- Coverage readiness requires >=100 fields, >=40 questions, >=8 unanswerable, every declared
  available collection/source language, all required case tags, and zero declared prior-key overlap
  in holdout sections. Missing source coverage stays in `coverage_gaps`; it is not supplied by models.
- D4 measurement requires >=95% field correctness, zero unsupported annotated slots and no
  ambiguous name alignment. Hidden expected conflicts lower field correctness.
  Coverage remains a separate gate. A 100% score on one field cannot meet the held-out requirement.

## Verification

```powershell
# This sandbox may require a writable pytest temporary directory.
$env:TEMP = Join-Path (Get-Location) '.lead/test-tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
& $evalPython -m pytest -q tests/unit/test_record_golden.py
& $evalPython -m ruff check packages/evaluation tests/unit/test_record_golden.py
```

Tests use neutral synthetic sources and block network sockets during the CLI measurement test.
Synthetic success proves scorer behavior only; it is never a hotel measurement or a replacement
for the independently human-checked local golden.

When only per-document WP41 outputs are available, score each document against its own annotated
record ids and report the per-document denominators. A multi-document i18n or conflict expectation
will fail until merged Records are saved. Documents without primary expected fields have an
undefined correctness denominator, even if they supply secondary Evidence. Report these gaps
alongside the aggregate; do not turn an undefined score into zero or one.
