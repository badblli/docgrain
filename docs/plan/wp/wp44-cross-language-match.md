# wp44-cross-language-match — Recognize the same thing across languages and documents

- Özet: Farklı dil ve belgelerdeki aynı kaydı (ör. "Standard Land View Room" = "Kara Manzara Standart Oda") öneri olarak eşleştir; birleştirme motoru bu önerilerle tek kayıt üretsin.
- Model: derin
- Phase: D4
- Branch: `codex/wp44-cross-language-match` (base: `origin/codex/wp42-record-merge`)
- Depends on: wp41 (merged), wp42 (lead approved, PR pending)
- Role: implementer

## Goal
wp42 merges records only by explicit source identity, aliases or the same normalized name in the
same language. Prime Beach has the same room types and outlets in EN/TR/DE/RU documents, so today
they stay separate. Produce reviewable alias proposals so they become one record each.

## Lead decisions (from wp42 questions)
- `source_identity` = record type + normalized primary name within one document.
- Previously distinct record ids merge only through an explicit alias decision; never silently.
- Proposals are `review_state: proposed` and carry their reasons.

## Tasks
1. `docgrain_records/match.py`: candidate pairs per record type across documents; score with
   deterministic signals first (same numbers: m², capacity, hours, prices; shared tokens after
   transliteration/casefold; same position in parallel documents) and, optionally, an
   OpenAI-compatible model that only answers "same / different / unsure" for a pair (client off
   unless configured; prompt treats document text as data).
2. Output `match_proposals.json`: pairs with score, signals, decision; and convert accepted
   proposals into wp42 aliases/decisions (no merge-engine changes beyond a small adapter).
3. CLI: `docgrain-records match --records <dir with per-document records.json> --out <dir>` and
   `docgrain-records merge --records <dir> --matches <file> --out <dir>` producing per-type JSON
   files (`room_type.json`, `outlet.json`, …) with EN-first primary values, i18n, conflicts.
4. Tests (synthetic): numeric agreement links translated names; conflicting numbers stay separate
   but are flagged; ambiguous pairs stay unmerged; model "unsure" never auto-merges.
5. Run deterministic matching (no model) on the real files in
   `C:/Users/root/Documents/projects/docgrain/data/records/primebeach/*/records.json` and report
   how many records per type collapse (expected ~7 room types, ~8 outlets) and which stayed apart.
   Write outputs inside your worktree under `data/` (ignored).

## Acceptance criteria
- [ ] Ruff + pytest clean (repo venv); no model calls in tests.
- [ ] Real Prime Beach deterministic run reported with counts and examples of merged/unmerged.
