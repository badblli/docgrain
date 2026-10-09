# wp112-dene-real-data — Dene must answer list questions on real companies

- Özet: Gerçek bir şirkette Dene tekil sorulara kaynaklı cevap veriyor ama "Hangi restoranlar var?" zaman aşımına düşüyor, "Hangi havuzlar var?" kayıtlar varken "Bilmiyorum" diyor; liste sorularını kaynaklı ve hızlı cevaplasın.
- Model: derin
- Engine: claude
- Phase: U1
- Branch: `codex/wp112-dene-real-data` (base: `origin/dev`)
- Depends on: WP94, WP103, WP111 (merged)
- Role: implementer
- Owner: Claude agent (Codex at its usage limit)

## Why (lead, first real Dene run, 2026-10-09; company with 106 records, 98.8 % approved)

- "Deluxe Standart Oda kaç kişilik ve kaç metrekare?" → correct, cited. "Helikopter pisti var mı?" → "Bilmiyorum." ✔
- "Otelde hangi restoranlar var?" (25 restaurant records) → "Yanıt zamanında alınamadı" (model call timeout is 20 s
  in `apps/api/docgrain_api/try_ai.py`).
- "Hangi havuzlar var, ısıtmalı olan var mı?" (13 pool records) → "Bilmiyorum." The per-sentence citation rule in
  `packages/access/docgrain_access/ask.py` (plus WP103's single repair) still rejects long list answers.

## Goal

1. Timeouts: per model call 60 s (configurable), whole question bounded (e.g. 120 s); clear Turkish message on
   timeout stays.
2. List questions: the model can fetch a collection in one tool call (`list_collection` with the fields needed);
   a list answer cites each item (one citation per bullet/line is enough; a heading line without facts needs no
   citation). Keep: unknown facts abstain, no source the model did not read, no invented items — every listed
   item must exist in the approved collection.
3. Measure on the live stack with `benchmarks/dene_abstain.py` (WP103) and a private question file for one real
   company (the lead runs it): known single-fact, known list, unknown questions; report correct-with-sources,
   abstained-on-known, answered-on-unknown (must stay 0), invented items (must stay 0), latency.

## Rules

Do not delete code (mark replaced code "KULLANILMIYOR (karar 18)"). No real model in tests (fake transports).
API contract of `POST /ai/ask` unchanged.

## Acceptance criteria

- [ ] Fake-model tests: list answer with one citation per item accepted; an item not in the collection → rejected;
      unknown → abstain; timeout path.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the lead's live command.
