# wp45-primebeach-golden — Held-out record quality measurement

- Özet: Otel belgeleri için bağımsız alan ve soru cevap anahtarı hazırlayıp bilgi doğruluğunu ölç.
- Model: derin
- Phase: D4
- Branch: `codex/wp45-primebeach-golden` (base: `origin/dev` after dependency review)
- Depends on: wp41-record-extractor, wp42-record-merge
- Role: implementer
- Owner: Bulbasaur / ece

## Goal

Measure meaningful record fields against a human-checked held-out golden, including omissions,
wrong language selection and invalid Evidence; JSON validity alone is not success.

## Scope

- In: offline scoring in `packages/evaluation/`, synthetic tests, measurement documentation.
- In (local ignored only): source manifest, held-out field golden/questions and results in `.lead/`.
- Out: extractor tuning, source edits, API/web changes, external model calls in this WP.

## Tasks

1. Inventory approved source files read-only in the local test hotel's folder supplied by the
   lead. Never enter or change `sonDB/` or `yeni db/`; never copy source text into tracked files.
2. Write a local manifest of file hashes, SourceVersion/document ids, languages and split.
   Freeze holdout source sections before inspecting predictions; record overlap with prior goldens.
3. Human-check at least 100 fields covering every available hospitality collection, all source
   languages, tables, units, negative/missing values and cross-document conflicting facts.
   Store expected primary/i18n values and exact document/locator/quote Evidence locally only.
4. Prepare at least 40 source-answerable/explicitly unanswerable questions (at least 8 unanswerable)
   with expected record/field ids and Evidence; document missing source coverage honestly.
5. Score saved records offline: field precision/recall, omissions, EN-first errors, conflict
   handling and Evidence validity. Correctness = correct expected fields / all expected fields;
   omissions stay in this denominator. Count unsupported extra fields separately in precision.
6. Add neutral synthetic scorer tests; report denominators and per-collection failures without
   leaking customer facts. Provide reproducible local commands and result locations to the lead.

## Acceptance criteria

- [ ] Repo venv `python -m pytest -q tests/unit/test_record_golden.py` passes without network.
- [ ] Repo venv `python -m ruff check packages/evaluation tests/unit/test_record_golden.py` passes.
- [ ] Frozen held-out manifest, >=100 verified fields and >=40 questions (>=8 unanswerable) exist
  locally; coverage gaps and any overlap are documented, never silently replaced with predictions.
- [ ] Scorer detects omitted fields, wrong English selection, invented quotes and hidden conflicts.
- [ ] Report measured field correctness against the D4 >=95% target and 0 unsupported fields;
  failing results remain failing and include actionable breakdowns, not automatic acceptance.
- [ ] No real source/golden contents or customer names enter code/tests/README; no model calls.

## Notes

Read `docs/plan/ROADMAP.md`, wp11, wp12, wp14, wp41 and wp42 specifications.
The lead supplies the local source path/document ids; customer artifacts remain outside Git.
Question answering on two models is a later D5 evaluation; this WP prepares its held-out inputs.
