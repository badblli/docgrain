# wp51-collection-discovery — Discover collections from the content, for any kind of company

- Özet: Sabit otel şeması yerine, şirketin normalize edilmiş belgelerinden tekrar eden yapıları (liste, tablo, kartlar) bularak koleksiyonları ve alanlarını AI yardımıyla öner: ör. odalar listesi varsa adı "rooms" olsun.
- Model: derin
- Phase: D4
- Branch: `codex/wp51-collection-discovery` (base: `origin/dev`)
- Depends on: wp46/wp47 (merged)
- Role: implementer

## Goal
Companies are not only hotels. Collections must be discovered per workspace from the normalized
content, named in English (token-cheap, stable keys) with localized labels, and be reviewable.

## Tasks
1. Deterministic signals: tables with repeated rows/columns, lists of similar items, repeated
   heading/field patterns ("X: value" blocks), recurring units/times/prices across documents.
2. AI proposal (OpenAI-compatible, off unless configured): given signals + samples, propose
   collections `{key, label_i18n, description, fields:[{key, type, unit?, label_i18n}], examples
   with evidence}`; strict JSON; every example must cite verified quotes (reuse extractor checks).
3. Stable keys: snake_case English plural nouns (`rooms`, `opening_hours`, `menu_items`), merged
   across documents of the workspace; output `schema.proposed.json` with review_state per
   collection/field; an accepted schema is versioned (`schema.v<N>.json`).
4. The existing hospitality models become one fixture/example, not the runtime schema.
5. Tests with synthetic non-hotel content (e.g. a clinic price list, a gym schedule) and a fake model.

## Acceptance criteria
- [ ] Ruff + pytest clean; no real model calls in tests.
- [ ] Report the command for the lead to run discovery on a workspace with a real model.
