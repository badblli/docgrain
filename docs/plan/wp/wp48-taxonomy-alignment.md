# wp48-taxonomy-alignment — One vocabulary for extractor, merge and golden

- Özet: Çıkarıcı ile cevap anahtarı için ortak sözlük (ne kural, ne tesis, ne ayrı ücret kaydı), sahte çelişkileri önleyen değer normalizasyonu ve serbest metni anahtar bilgilere göre puanlama.
- Model: derin
- Phase: D4
- Branch: `codex/wp48-taxonomy-alignment` (base: `origin/codex/wp47-end-to-end-merge`)
- Depends on: wp45, wp46, wp47
- Role: implementer

## Evidence (wp47 real run, Prime Beach)
- The extractor finds "Evcil Hayvan Politikası", "Sigara İçme Politikası", but policy text is a
  paraphrase → exact-text scoring fails (policy 2/16).
- Golden files "Wi-Fi", "Otopark", "Bebek yatağı" as policy; the extractor files them as
  facility/service. Golden splits "18:00'e kadar geç çıkış" / "23:00'e kadar geç çıkış" as two prices;
  extractor makes one "Geç Check-out".
- Trivial conflicts: "1 çift kişilik yatak veya 2 tek kişilik" (string) vs ["1 çift…","2 tek…"] (list)
  leave `primary: null`.

## Tasks
1. `packages/records/TAXONOMY.md` (+ machine-readable `taxonomy.json`): definitions, boundaries and
   granularity rules per collection with neutral examples (policy vs facility vs service_price;
   one service_price record per priced option/time limit; amenities in room features vs facility).
   The extractor prompt includes the relevant rules per pass.
2. Value normalization before conflict detection: list splitting on "veya/or/oder/или", ",", ";";
   whitespace/case/diacritics; numbers with units; time ranges (reuse docgrain_eval.scoring).
   Equal-after-normalization values merge evidence instead of conflicting.
3. Scorer (wp45 `record_golden.py`): free-text fields (policy text, descriptions) scored by key-fact
   overlap (numbers, times, prices, negations like "kabul edilmez", key nouns) with a threshold;
   alignment allows an expected record to match a predicted record of a neighbouring collection
   (report it as "type mismatch", counted separately).
4. Golden review: list golden items whose collection/granularity contradicts TAXONOMY.md; do NOT
   edit the golden — write the list to your report for the lead.
5. Re-score the wp47 outputs (no model calls) and report per collection.

## Acceptance criteria
- [ ] Ruff + pytest clean (repo venv); tests for normalization and key-fact scoring.
- [ ] Before/after scores on the same saved outputs; trivial-conflict count before/after.
