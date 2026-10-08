# wp102-labelled-evidence — Evidence quotes must identify the field, not just the value

- Özet: Bir alanın kanıtı yalnızca "32" gibi çıplak bir değer olamasın; alıntı değeri, alanı tanıtan etiketle ya da aynı satırdaki bağlamla birlikte göstersin ki belgedeki başka bir "32" yanlışlıkla kanıt sayılmasın.
- Model: derin
- Engine: codex
- Phase: D18
- Branch: `codex/wp102-labelled-evidence` (base: `origin/dev`)
- Depends on: WP99 (`verify.py`, merged)
- Role: implementer
- Owner: Charizard (codex)

## Why (lead, live U1 smoke 2026-10-08)

Published evidence for `rooms.size = 32` was the quote `"32"`; `"2"` for capacity. Verification only checks that
the quote occurs in the source, so any other "32" in the document would also pass. The product promise is
"zero unsupported fields", which needs evidence that ties the value to the field.

## Goal

1. In `packages/records/docgrain_records/verify.py`, a quote is accepted for a field only when it (a) contains the
   value (existing rule) and (b) is not a bare value: it must contain at least one non-value word or label token
   from the same source line/cell (e.g. "Büyüklük: 32 m2", "32 m²", "Kapasite: 2 kişi"), or the source line itself
   consists only of the value and its row/column header is recorded in the locator (tables). Define this
   precisely and keep it language-neutral (TR/EN/DE/RU).
2. When the model returns a bare value quote, widen it deterministically to the smallest span of the same
   source line that satisfies the rule (no model call), and keep the widened quote as evidence. If no such span
   exists, reject the field as today (`RejectedField` with a new reason code).
3. Extraction prompt (`extractor.py`) asks for the label-bearing quote explicitly; the verifier stays the authority.
4. Measure on the existing tests and fixtures: how many accepted fields change, and on the U1 fixture the quotes
   become "Büyüklük: 32 m2" and "Kapasite: 2 kişi".

## Acceptance criteria

- [ ] Bare value quotes are widened or rejected; tests cover numbers, times ("08:00–20:00"), names, table cells.
- [ ] No previously correct field in the existing test corpus is lost without a stated reason.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with before/after examples.
