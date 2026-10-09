# wp111-auto-accept-and-normalized-conflicts — Ask only real conflicts

- Özet: Tek belgede geçen ve kaynak alıntısı doğrulanmış, çelişkisi olmayan alanlar otomatik onaylansın (karar 20); "10:00 / 18:00" ile "10:00–18:00" gibi yalnız yazımı farklı değerler çelişki sayılmasın; Sorular'da yalnız gerçek çelişkiler ve tekrarlar kalsın.
- Model: derin
- Engine: claude
- Phase: U1
- Branch: `codex/wp111-auto-accept-and-normalized-conflicts` (base: `origin/dev`)
- Depends on: WP110 (merged)
- Role: implementer
- Owner: Claude agent (Codex at its usage limit)

## Why (first demo runs, 2026-10-09)

Two real companies: 106 and 124 records, 0 unsupported fields — but 421 and 377 questions, 415 and 351 of them
`needs_review` for single-source, verified, non-conflicting fields. Among the conflicts, several are formatting
only ("10:00 / 18:00" vs "10:00-18:00", "24 saat" vs "24 saat" from two quotes) or OCR typos in long descriptions
("konsantre" vs "konsanire"). User decision 20 (2026-10-09): auto-accept verified single-source fields.

## Goal

1. Auto-accept (decision 20): at merge/publish time, a field value whose candidates all agree (one source, or
   several sources with equal normalized values) and whose evidence passed `verify.py` is `accepted` with
   reviewer `rule:verified-single-source` (or `rule:verified-agreeing-sources`) recorded in the revision, so it is
   auditable and reversible; the user can still change it (existing answer/correction API). It appears in the
   approved publication. Conflicts, duplicates, schedule swaps and anything the verifier flagged stay questions.
2. Normalized comparison before declaring a conflict, per value kind: times and time ranges ("10:00 / 18:00",
   "10:00-18:00", "10.00 – 18.00" equal), numbers with units ("25-27 m 2" vs "25–27 m²"), whitespace/case/
   punctuation/Unicode dashes, Turkish casing (İ/ı). Long free text: treat as the same value when the normalized
   strings are near-identical (e.g. ≥ 0.95 similarity on characters) — keep the better-sourced candidate and record
   the alternative as a variant, not a question. Never merge different numbers or different times.
3. Re-publish existing workspaces without re-extraction: a lead command that re-runs merge + publish on the last
   job's runtime directory (or a documented API path) so the two demo companies get the new rules.
4. Report counts before/after on the two companies (the lead runs it; give the command).

## Rules

Do not delete code (mark replaced code "KULLANILMIYOR (karar 18)"). Keep "conflicts are asked, never guessed":
only formatting-equal values merge. No network in tests.

## Acceptance criteria

- [ ] Tests: single-source verified → accepted with the rule reviewer; two sources equal after normalization →
      accepted, no question; different times/numbers → conflict question; near-identical long text → one value plus
      variant, no question; unverified evidence → still a question.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean, tsc 0. Report (Turkish) with the lead's command.
