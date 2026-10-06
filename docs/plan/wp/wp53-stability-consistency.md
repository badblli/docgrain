# wp53-stability-consistency — Measure hallucination-free, stable knowledge across companies

- Özet: Dört şirkette aynı hattı çalıştırıp ölç: kanıtsız alan oranı (hedef 0), aynı belgeleri iki kez işleyince aynı kayıtların çıkma oranı, şirketler arası tutarlılık ve bağımsız anahtarla alan doğruluğu.
- Model: derin
- Phase: D4
- Branch: `codex/wp53-stability-consistency` (base: `origin/codex/wp52-schema-driven-records`)
- Depends on: wp50, wp51, wp52
- Role: implementer

## Metrics
- Unsupported field rate: published fields whose quote is not in the pinned source (target 0).
- Run-to-run stability: extract+merge twice on identical inputs → share of identical records/fields.
- Coverage: share of source list/table rows that ended up in some record.
- Accuracy: wp45-style field golden per company (Prime Beach exists; add a small key per other company).
- Cross-company report: discovered collections per company, sizes, conflicts.

## Acceptance criteria
- [ ] `docgrain-eval stability …` and a cross-company report; no golden edits after seeing predictions.
