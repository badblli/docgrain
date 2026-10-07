# wp69-fast-matching — matching that scales to a 130-page company

- Özet: Kayıt eşleştirme büyük şirkette 2 saati aştı (784 aday kayıt, her aday çift için model çağrısı); önce kurallarla ve isim benzerliğiyle karar ver, modele yalnızca belirsiz çiftleri sor, işi paralel ve kaldığı yerden devam edebilir yap.
- Model: derin
- Engine: codex
- Phase: D4
- Branch: `codex/wp69-fast-matching` (base: `origin/dev`)
- Depends on: wp67 (merged first)
- Role: implementer

## Finding (lead, real workspace)

`docgrain-records match` on a workspace with 7 documents / 129 pages / 784 candidate records ran > 2 h and
was stopped; a smaller workspace (13 documents, ~300 candidates) took ~30 min. The judge model is called
per candidate pair; most pairs are obvious (exact/normalized same name in the same collection, or clearly
different).

## Tasks

1. Blocking: only compare records of the same collection; build candidate pairs from a cheap key
   (normalized name tokens, transliteration TR/EN/DE/RU, numbers) instead of all pairs.
2. Deterministic decisions first: exact/normalized identity match → `strong` (auto-accept rule as today);
   no shared token and different key fields → `no-match`. Only the ambiguous middle goes to the model.
3. Model calls: batch several ambiguous pairs per request (bounded prompt size), up to N concurrent
   requests (default 4), retries on 429/5xx/timeouts.
4. Resumable: write decisions incrementally (`match_progress.jsonl`); a restart skips decided pairs; the
   final `match_proposals.json` is identical in format to today's.
5. Progress line on stderr every ~20 s (pairs decided / total, model calls, elapsed); a `--max-minutes`
   budget that stops cleanly and resumes later.
6. Tests with synthetic data: blocking keeps true matches, deterministic rules decide the obvious pairs,
   only ambiguous pairs reach the fake model, batching/concurrency/resume produce identical proposals.

## Acceptance criteria

- [ ] `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass.
- [ ] Report: model calls and pairs before/after on a synthetic 800-record workspace; the command for the
      lead's real run.
