# wp114-structure-context — Use document structure when consolidating records

- Özet: Belgedeki başlık, bölüm ve tablo başlıkları toparlamada kullanılsın: aynı ad farklı kat/daire/bölüm altında tekrar ediyorsa ayrı kayıt olsun, başlıktan gelen kategori başlığın kendisiyle kanıtlansın; her şirket için toparlama kalite raporu çıksın.
- Model: derin
- Engine: codex
- Phase: U1
- Branch: `codex/wp114-structure-context` (base: `origin/dev`)
- Depends on: WP110, WP111 (merged)
- Role: implementer
- Owner: Porygon (codex)

## Why (lead review of real extractions, 2026-10-12)

Focus is consolidating company data correctly (user, 2026-10-12).
- A floor-plan PDF (one document, several floors/units): every floor has "Hol", "Oda 1", "Banyo". Records with the
  same name inside one document were merged, so the company got 24 records and 24 "conflicts" (e.g. "Hol / Alan:
  16,83 m² (§134) | 13,27 m² (§95) | 16,85 m² (§48)", "Hol / Kat: ALT KAT | ÇATI KATI"). These are different rooms.
- Designed menus: 149 of 155 rejected fields were `category` with `bare_value_quote`. The category of a dish is
  the section heading it sits under ("Çorba / Soup"); the heading line is the evidence, but WP102's label rule
  rejects a short category quote standing alone.

## Goal

1. Structure context: every extracted record carries its structural context from the canonical snapshot (heading
   path / section title / table row and column headers) next to its evidence. In-document coalescing
   (`_coalesce_document_records` and anything else that merges by name inside one document) only merges records
   with the same name when their structural context agrees (or one has none). Records with the same name under
   different contexts become separate records; their display title may add the distinguishing context
   ("Hol — Çatı Katı"). Cross-document matching may use the context as a signal; it must not merge records whose
   contexts conflict.
2. Heading evidence: a label-dependent value (category, type, floor, section) whose quote is the heading/section
   title that structurally contains the record's own evidence is valid evidence (record the heading locator).
   Bare values not backed by such structure stay rejected (WP102 rule unchanged otherwise).
3. Quality report `benchmarks/consolidation_report.py` (lead runs it on the live stack per workspace): records per
   collection; suspected over-merges (records whose conflicting candidates come from the same document at
   different structural contexts); suspected under-merges (records in the same collection with highly similar or
   translated names — use the existing name normalization and a TR/EN/DE/RU dictionary-free similarity, no model);
   conflicts split into real/format-only; rejected fields by reason; unsupported fields (must be 0). JSON + Markdown.
4. Re-run path: the existing `republish` (WP111) cannot fix in-document merges because records are already
   coalesced at extraction; document how to re-run Bilgileri çıkar for one company and measure before/after with
   the report.

## Rules

Do not delete code (mark replaced code "KULLANILMIYOR (karar 18)"). Keep "conflicts are asked, never guessed".
No network/real model in tests; use synthetic snapshots (a floor plan with repeated room names under two floor
headings; a menu with dishes under category headings).

## Acceptance criteria

- [ ] Synthetic floor plan → separate records per floor, no false conflicts; same room repeated under the same
      heading still merges.
- [ ] Synthetic menu → categories accepted with heading evidence; a bare category without structure still rejected.
- [ ] Report script runs on fake data and lists over/under-merge suspects.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the lead's live commands.
