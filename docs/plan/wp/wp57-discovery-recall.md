# wp57-discovery-recall — discovery must find every list a company's documents contain

- Özet: Koleksiyon keşfi gerçek şirketlerde çok az liste buluyor (ör. bir otelde sadece "havuzlar"); tüm belgeleri tarayıp eksik kalan bölümler için yeniden soran, kapsamı ölçülen bir keşif yap.
- Model: derin
- Phase: D4
- Branch: `codex/wp57-discovery-recall` (base: `origin/dev`)
- Depends on: wp51, wp52 (merged)
- Role: implementer

## Problem (measured by the lead on 2026-10-06, Gemini 3.7 Flash, real workspaces)

| workspace | signals | proposed collections |
| --- | --- | --- |
| hotel A (7 files, 45 pages) | 31 | bars, faqs, rooms |
| hotel B (13 txt) | 31 | activities, bars, restaurants |
| hotel C (13 pdf, 56 pages) | 9 | swimming_pools |
| hotel D (7 files, 129 pages) | 21 | rooms |

For hotel A the fixed hotel schema found 8 collections / 307 records on the same documents
(rooms, outlets, activities, facilities, policies, contacts, properties, service_prices). Discovery
therefore misses most lists. Plain text and OCR-heavy PDFs yield very few structural signals.

## Tasks

1. Find why so few signals: read `discovery_signals.py` and run it on the synthetic fixtures plus a
   plain-text fixture (headings + bullet lists, no tables) and an OCR-like fixture (short lines, noise).
   Signals must come from headings, bullet/numbered lists, repeated label:value lines, tables, and
   section text — not only tables/fields.
2. Coverage loop: after a proposal, compute which sections/blocks are not covered by any proposed
   collection (by evidence locators); if uncovered content is substantial, ask again with only those
   sections (bounded rounds, e.g. 3), then merge proposals (same key → union of fields, keep conflicts).
3. Report `coverage` in the discovery output: share of content blocks (by characters) that fall under
   some collection, plus the uncovered section titles.
4. Keep quotes verified, model off by default, prompt size bounded (`--max-prompt-chars`); several
   requests are fine.
5. Tests: plain-text hotel fixture must yield ≥ 6 collections with a fake model that answers per
   section; a coverage-loop test where the first answer misses sections and the second round fills them.

## Acceptance criteria

- [ ] Ruff + pytest clean (repo venv).
- [ ] New fixtures/tests above pass; discovery output includes `coverage` and `uncovered`.
- [ ] Report: the root cause in two sentences and the exact command the lead should run on the real
      workspaces (the lead runs it; you have no network).

## Notes

- You run sandboxed, no network, no real customer documents: use synthetic fixtures only.
