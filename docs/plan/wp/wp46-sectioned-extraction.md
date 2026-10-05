# wp46-sectioned-extraction — Extract every policy, price and activity, not just the first few

- Özet: Çıkarıcı uzun belgeleri bölüm bölüm ve koleksiyon koleksiyon işlesin; kurallar, ücretler ve etkinlikler atlanmasın (hedef: Prime Beach alan doğruluğu %60 → %90+).
- Model: derin
- Phase: D4
- Branch: `codex/wp46-sectioned-extraction` (base: `origin/codex/wp44-cross-language-match`)
- Depends on: wp41, wp44
- Role: implementer

## Evidence
Held-out Prime Beach golden (wp45, local `data/golden/primebeach/`): 88/147 fields correct.
Contacts 12/12, rooms 30/37, outlets 26/35 — but policies 1/16, service prices 1/14, activities 2/8,
facilities 13/22, almost all **omissions**. One model call per whole document under-extracts long
lists.

## Tasks
1. Split a document's compact context into sections (headings / block ranges, ~6–10k chars each,
   keep §N keys intact) and extract per section; merge section results with the existing
   same-document same-name collapse (wp44).
2. Add a collection-focused pass for list-heavy types (policy, service_price, activity, facility):
   the prompt asks for **all** items of that type in the section, with a completeness reminder.
3. Keep every guarantee: verified quotes per cited block, EN-first, i18n, conflicts, source pins.
4. Cost/latency guard: parallel requests with a small concurrency limit, retries; record per-call
   token usage in `source.json` (`usage` totals).
5. Unit tests with a fake transport: multi-section document yields items from every section;
   duplicate item across sections collapses; a section failure is reported, others kept.

## Acceptance criteria
- [ ] Ruff + pytest clean (repo venv); no real model calls in tests.
- [ ] Report the exact re-extraction command; the lead re-runs Prime Beach and the wp45 scorer.
