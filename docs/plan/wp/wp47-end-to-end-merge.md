# wp47-end-to-end-merge — Prime Beach end to end: one JSON per collection

- Özet: Gerçek Prime Beach verisinde çıkarım → eşleştirme → birleştirme zincirini uçtan uca çalışır hâle getir; sonuç koleksiyon başına tek JSON (room_type.json, outlet.json…) ve ölçüm.
- Model: derin
- Phase: D4
- Branch: `codex/wp47-end-to-end-merge` (base: `origin/codex/wp46-sectioned-extraction`)
- Depends on: wp42, wp44, wp46
- Role: implementer

## Evidence (real run by the lead, local, ignored)
- Section-wise records: `C:/Users/root/Documents/projects/docgrain/data/records/primebeach-v2/<doc>/`
  (records.json, source.json, context.md) — 7 documents, ~500 records.
- `docgrain-records match` → 15,416 proposals (almost all pairs; needs pruning).
- `docgrain-records merge` → "merge requires verified evidence in the pinned source context":
  section-wise evidence does not pass the merge verification.

## Lead decisions
- Strong deterministic matches (same type, name similarity above threshold AND agreeing numeric
  signals, or identical normalized name) are accepted by rule: write decisions with
  `reviewer: "rule:<rule-name>"` so they stay visible and reversible. Everything else stays
  `proposed` and is listed for review. Model judge stays optional and never accepts "unsure".
- Prune candidates before scoring pairs: same type, plus name/number blocking; report counts.

## Tasks
1. Make merge verification accept wp46 evidence (same quote/locator rules the extractor used);
   add a regression test built from a synthetic multi-section document.
2. Candidate pruning + `--auto-accept strong` in `match`/`merge`.
3. Run on the real files (copy them into your worktree `data/` if needed; no model calls):
   produce `merged/<collection>.json` with EN-first values, i18n, conflicts, sources, review state.
4. Score with the wp45 scorer against `data/golden/primebeach/` from
   `C:/Users/root/Documents/projects/docgrain-wt/wp45-primebeach-golden/` (read-only) — per
   document AND merged; report accuracy per collection and examples of remaining misses.

## Acceptance criteria
- [ ] Ruff + pytest clean (repo venv).
- [ ] Real run completes: counts per collection before/after merge; proposals pruned (state numbers).
- [ ] Scorer numbers reported; no golden changes.
