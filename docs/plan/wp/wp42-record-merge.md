# wp42-record-merge — Source-linked record merge and field history

- Özet: Aynı kaydı farklı belge ve dillerden birleştir; çelişkileri görünür tut ve değişen alanları kaynaklarıyla göster.
- Model: derin
- Phase: D4
- Branch: `codex/wp42-record-merge` (base: `origin/dev` after dependency review)
- Depends on: wp41-record-extractor
- Role: implementer
- Owner: Alakazam / bora

## Goal

One real item has one stable Record id across documents, languages and revisions.
Conflicting facts remain reviewable; a new source version produces a field-level diff.

## Scope

- In: `packages/records/docgrain_records/`, synthetic unit tests, usage documentation.
- Out: API/web changes, model calls, automatic acceptance, document re-ingestion.

## Tasks

1. Define a workspace-scoped merge contract using wp41 models and Evidence; pin each document
   to SourceVersion/KnowledgeRevision ids. Model field-level ReviewState and explicit review
   decisions so accepted values can be distinguished from unresolved candidates by exporters.
2. Match by explicit source identity/aliases and deterministic normalized keys; do not merge
   ambiguous items merely because names resemble each other. Preserve unmatched candidates.
3. Persist an identity mapping so edits, translations and input order cannot change existing ids.
4. Select English as primary per field when available; keep other languages in `i18n` with
   their Evidence. Missing English fields may use an evidenced fallback with its actual lang.
5. Coalesce equal facts and union Evidence. Preserve differing same-language values as visible
   conflicts with candidates, source versions and ReviewState; never silently overwrite them.
6. Compare revisions by stable id and field: added/removed/changed values, i18n, Evidence and
   conflicts. Preserve the old revision and distinguish Evidence-only changes from fact changes.
7. Provide an offline example and tests for ambiguity, EN-first, repeated merge, reordered input,
   cross-document conflicts, deletion and a one-field source-version change.

## Acceptance criteria

- [ ] Repo venv `python -m pytest -q tests/unit/test_record_merge.py` passes without network.
- [ ] Repo venv `python -m ruff check packages/records tests/unit/test_record_merge.py` passes.
- [ ] A synthetic EN/TR pair merges once; English wins and translated fields retain Evidence.
- [ ] Input reorder/repeat and a renamed matched record retain ids; ambiguous matches stay separate.
- [ ] Conflicting values and their sources are inspectable; no candidate is silently accepted.
- [ ] One changed field yields exactly one value change; old revision remains queryable in example.
- [ ] Every resulting field has verified Evidence; fixtures contain only neutral synthetic data.

## Notes

Read `docs/plan/ROADMAP.md`, `AGENTS.md`, and `docs/plan/wp/wp41-record-extractor.md`.
Finalize concrete model names after wp41 approval; report unresolved identity policy to the lead.
