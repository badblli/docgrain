# wp113-speed — Make Bilgileri çıkar and Dene fast enough for a live demo

- Özet: Bilgileri çıkar şirket başına 28–38 dakika, Dene cevapları 24–120 saniye sürüyor ve 25 kayıtlı restoran listesi zaman aşımına düşüyor; zamanın nereye gittiğini ölç, doğruluğu düşürmeden hızlandır.
- Model: derin
- Engine: codex
- Phase: U1
- Branch: `codex/wp113-speed` (base: `origin/dev`)
- Depends on: WP110, WP111, WP112 (merged)
- Role: implementer
- Owner: Porygon (codex)

## Why (lead, live runs 2026-10-09)

- Bilgileri çıkar: 8 documents → 28 min (discover 4 min, extract ~24 min with 4 parallel calls); 5 documents →
  38 min. Worker CPU stays ~0 %: the time is model generation (Gemini `gemini-3.7-flash` through the
  OpenAI-compatible endpoint).
- Dene: single facts 24–29 s, a 13-item list 69 s, a 25-item list hits the 120 s question limit.

## Goal

1. Measure first (no behaviour change): per stage and per model call record wall time, prompt/completion/
   reasoning tokens (if the provider returns them), retries; write them into job metadata and the Dene benchmark
   output. Produce a table for one demo company (the lead runs the real calls).
2. Model call options per workspace: allow an optional `reasoning_effort` (or the provider's equivalent, e.g.
   Gemini's OpenAI-compatible `reasoning_effort`: verify the accepted values in the provider docs; do not guess)
   and `max_tokens` in the workspace model settings (API + Ayarlar, default unchanged), passed by every client
   (extraction, discovery, match judge, Dene). Never put keys in settings.
3. Extraction: fewer and smaller calls without losing fields — e.g. send each section once with all collections
   that apply instead of one call per collection when the plan allows it, and raise the parallelism limit to a
   configurable value (default 6) with backoff on 429. Keep deterministic order and the verifier.
4. Dene: for list questions, let `list_collection` results be rendered into the answer with fewer model tokens
   (e.g. ask the model only to choose which records/fields answer the question and render the cited list on the
   server from the approved records), keeping "every listed item exists and is cited" and abstaining on unknown.
5. Benchmark script `benchmarks/speed.py` that runs (lead, real model): Dene question set (single, list,
   unknown) and a small extraction on a synthetic fixture, for each option set (effort none/low/medium); reports
   latency p50/p95, tokens, and correctness (Dene: WP112 scorer; extraction: fields vs the fixture key). The lead
   also runs the independent-key accuracy (`docgrain_eval.record_golden`) on one real company for the chosen
   setting.

## Rules

Do not delete code (mark replaced code "KULLANILMIYOR (karar 18)"). No real model in tests. Correctness gates
speed: a faster setting is only made default if correctness does not drop (Dene: no invented items/sources,
abstain on unknown; extraction: field accuracy within 1 point of the current setting).

## Acceptance criteria

- [ ] Timing/tokens recorded per stage and per call (tests with fake transports).
- [ ] Workspace setting for effort/max tokens, passed to all clients (tests).
- [ ] Extraction call count reduced on the fake model with identical records; Dene list rendering keeps the
      citation rules (tests).
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean, tsc 0. Report (Turkish) with the lead's commands.
