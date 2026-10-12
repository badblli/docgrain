# wp115-cross-language-duplicates — The same place named in different languages is one record

- Özet: Farklı belgelerde Türkçe, İngilizce, Almanca ya da Rusça adla geçen aynı yer (ör. "Fish restoran" / "balık", "Steakhouse" / "Steak House restoran") tek kayıt olsun; güçlü kanıt varsa birleşsin, emin değilse "bunlar aynı yer mi?" diye sorulsun.
- Model: derin
- Engine: codex
- Phase: U1
- Branch: `codex/wp115-cross-language-duplicates` (base: `origin/dev`)
- Depends on: WP111 (merged); coordinate with WP114 (structure context) — no shared files except tests
- Role: implementer
- Owner: Charizard (codex)

## Why (lead review, 2026-10-12)

A company's approved restaurant list contains pairs that are the same place: "Steakhouse" / "Steak House restoran",
"Fish restoran" / "balık", "Chinese restoran" / "Çin", "Bistro restoran" / "bıstro restaurant",
"Italian restoran" / (Italian). They come from a Turkish fact sheet, an English FAQ and an Excel with opening hours.
They were neither merged nor asked as duplicate questions.

## Goal

1. Read the current match pipeline first (`packages/records/docgrain_records/match.py`, `match_merge.py`,
   `merge.py`, `duplicates.py`, `normalize.py`, and the identity/alias logic) and the record `i18n` model (fields
   carry per-language values). Explain in the report why these pairs were missed.
2. Candidate generation across documents in the same collection: normalized names, records' own i18n names,
   generic-word stripping per language ("restoran", "restaurant", "restaurante", "ресторан", "bar", "snack"…, a
   small fixed list in code), cuisine/category words mapped across languages with a small fixed bilingual table
   (fish/balık, chinese/çin, italian/italyan, steak/steakhouse…, documented and testable — no model needed for
   candidates), plus shared non-name signals (same opening hours, same location, same category).
3. Decision: merge automatically only with strong independent evidence (same name after generic stripping and
   translation AND at least one agreeing non-name field, no conflicting field); otherwise create a `duplicate`
   question with both records and their sources (existing question kind). Never merge on name translation alone
   when a field conflicts. An optional model judge may be used only for ambiguous pairs and only when the
   workspace model is on (existing behaviour); results stay questions unless evidence is strong.
4. Apply via the existing republish path (WP111) so the lead can update a company without re-extraction; report
   before/after duplicate counts.

## Rules

Do not delete code (mark replaced code "KULLANILMIYOR (karar 18)"). No real model in tests.

## Acceptance criteria

- [ ] Synthetic tests: TR/EN pairs with agreeing hours → merged with both names kept as i18n/aliases; pair with
      conflicting hours → duplicate question; unrelated "Bar" vs "Bistro" → untouched.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the root cause and the
      lead's republish command.
