# wp64-recurring-schedules — recognise recurring events and ask one precise question

- Özet: Tekrarlayan etkinliklerin tarihlerini tek tek sormak yerine kuralını çıkar ("2 haftada bir Cumartesi, 24 May–27 Eyl"); belgeler kuralda anlaşıyorsa soru sorma, yalnızca farkı ve gerekiyorsa iki etkinlik arasındaki yer değiştirmeyi tek soru olarak sor.
- Model: derin
- Engine: codex
- Phase: D4
- Branch: `codex/wp64-recurring-schedules` (base: `origin/dev`, after wp63 is merged)
- Depends on: wp61, wp63 (both touch `review.py`)
- Role: implementer

## Finding (lead, real workspace, values withheld)

Two weekly parties A and B alternate on Saturdays from late May to late September. Document 1 and
document 2 agree for May–June (3 shared dates each), then from July on the two documents list A's
Saturdays under B and B's under A (every date that is only in doc 1 for A is only in doc 2 for B, and vice
versa). Today the user is asked "A için Tarih hangisi?" with 16 single dates. The right question is one:
"Temmuz'dan itibaren A ve B'nin cumartesileri iki belgede yer değiştirmiş; hangi belge doğru?"

## Tasks

1. `packages/records/docgrain_records/schedule.py`: infer a recurrence from a set of dates (weekday(s),
   interval in days — 7/14 — first and last date, exceptions = missing or extra dates). Pure functions,
   deterministic; only for date fields with ≥ 3 values.
2. Publish recurring date lists with a readable summary next to the list (e.g. `schedule: {"weekday":
   "Saturday", "every_days": 14, "from": "2025-05-24", "to": "2025-09-27", "missing": [...],
   "label_tr": "2 haftada bir Cumartesi, 24 May – 27 Eyl 2025"}`); the dates stay the source of truth.
3. Question building for date conflicts between documents:
   - documents imply the same recurrence → no question, publish the union (with evidence from both);
   - they differ only by a few dates → one question about those dates, options grouped by document;
   - **swap detection** across records of the same collection: if record A's dates in doc 1 equal record
     B's dates in doc 2 for a period (and vice versa), emit ONE question of kind `schedule_swap` naming
     both records, the period ("Temmuz'dan itibaren"), and two options = the two documents' programs;
     answering accepts that document's dates for both records (use the `document_id` answer from wp63).
4. `GET …/questions` items for schedules carry `kind`, `records` (both titles), `period_label_tr`, and
   per option a short human summary of that document's program; the web shows them in the grouped card.
5. Tests with synthetic data shaped exactly like the finding (two alternating Saturday series, swap from
   July), plus: agreeing documents → no question; one extra date → one small question.

## Acceptance criteria

- [ ] `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass.
- [ ] The synthetic finding produces exactly one `schedule_swap` question instead of 2 × 16 date options.
- [ ] Report with before/after question counts (synthetic) and the exact command for the lead's real run.
