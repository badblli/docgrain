# wp103-dene-abstain-rate — Dene should not say "Bilmiyorum" when approved sources answer the question

- Özet: Dene onaylı ve kaynaklı bilgi varken ara sıra "Bilmiyorum" diyor; çekimserlik oranını ölç ve uydurma riskini artırmadan düşür.
- Model: derin
- Engine: codex
- Phase: U1
- Branch: `codex/wp103-dene-abstain-rate` (base: `origin/dev`)
- Depends on: WP94 (merged)
- Role: implementer
- Owner: Jigglypuff (codex)

## Why (lead, live smoke 2026-10-08)

On the same approved revision, "Bahçe Odası kaç metrekare ve kaç kişilik?" was answered correctly with sources 4
times and abstained once (the smoke run failed on that one). `ask_result` in
`packages/access/docgrain_access/ask.py` abstains when any sentence lacks a citation, so one uncited connective
sentence turns a correct answer into "Bilmiyorum".

## Goal

1. A measurement script `benchmarks/dene_abstain.py` (fake model for tests; real model only when the lead passes
   connection arguments): N repetitions of known and unknown questions on a published workspace; reports
   correct-with-sources, abstained-on-known, answered-on-unknown (must stay 0), invented sources (must stay 0).
2. Reduce abstain-on-known without weakening grounding: e.g. when a final answer fails only the per-sentence
   citation rule but every factual claim (numbers, names, times) is covered by a read source, ask the model once
   to rewrite with a citation on every sentence (same sources, no new tool calls); drop pure connective sentences
   that carry no fact. Unknown questions must still abstain.
3. Keep the API contract of `POST /ai/ask`.

## Acceptance criteria

- [ ] Fake-model tests: uncited connective sentence → rewritten and accepted; uncited fact → still abstains;
      unknown question → abstains; no source the model did not read can appear.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the lead's live command.
