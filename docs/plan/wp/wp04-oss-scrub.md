# wp04-oss-scrub — No partner product name in README or code

- Özet: README ve kodda iş ortağı ürün adı geçmesin (demo çalışma alanı adı, arayüz metni, test). Dokümanlar ve test verisi kapsam dışı.
- Model: hafif
- Phase: D0
- Branch: `codex/wp04-oss-scrub` (base: `origin/dev`)
- Depends on: none
- Role: lead (small enough to do directly)

## Decision (user, 2026-10-05)

The repository is open source and will be announced. A partner product name must not appear in
the README or in code (apps, packages, tests, scripts, configuration). Historical documents and
test data may keep their content. The term list lives outside Git in `.lead/scrub-terms.txt`.

## Done

- Demo fixture workspace id renamed to `ws_demo` (API fixtures and contract tests).
- Web console sentence about consumers replaced with a neutral one.
- README is rewritten separately (wp05).

## Acceptance criteria

- [x] No match in code paths (`git grep` excluding `docs/`).
- [x] `ruff` clean, `pytest` 390 passed / 89 skipped.
