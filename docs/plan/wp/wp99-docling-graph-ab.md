# wp99-docling-graph-ab — Docling Graph as an optional extract engine, measured against ours

- Özet: Kayıt çıkarma adımına isteğe bağlı Docling Graph motoru ekle; şablonu kabul edilmiş şemadan çalışma anında üret, çıktıyı her zaman bizim kanıt doğrulayıcımızdan geçir ve iki motoru aynı ölçütlerle karşılaştır.
- Model: derin
- Engine: codex
- Phase: D18
- Branch: `codex/wp99-docling-graph-ab` (base: `origin/dev`)
- Depends on: none
- Role: implementer
- Owner: Charizard (codex)

## Read first

`docs/plan/DOCLING-REUSE.md` sections 2–4, ROADMAP decision 18, and in `packages/records/docgrain_records/`:
`runtime.py`, `extractor.py`, `sections.py`, `models.py`, `cli.py`.

## Goal

1. Move field-evidence verification (`verify_response`, `normalize_quote` and what they need) into
   `packages/records/docgrain_records/verify.py` without behaviour change; `extractor.py` imports it.
2. New `packages/records/docgrain_records/graph_adapter.py`: build a Pydantic template at runtime from the
   accepted `WorkspaceSchema` / `RuntimeRecords` (root model with one list per collection, `graph_id_fields` =
   identity field), run docling-graph `run_pipeline` on the document (prefer the Docling-document input path so
   we do not convert twice), map its output to our `ExtractionResult`, and pass it through `verify.py`:
   unverifiable fields are rejected exactly as today. Two variants behind a flag: `plain` (values only,
   evidence recovered from Docling refs to our §N blocks) and `quoted` (template fields carry `{value, quote}`).
3. `extract --engine docgrain|docling-graph [--graph-variant plain|quoted]` in `cli.py`, default `docgrain`.
   The model comes from the same OpenAI-compatible arguments; pass the key through the docling-graph
   connection override, never by setting a process-wide environment variable.
4. Optional dependency group `graph` in `packages/records/pyproject.toml` with `docling-graph==1.9.1` and an
   exact LiteLLM pin (not 1.82.7 or 1.82.8). The lead installs it; when it is missing the engine fails with a
   clear message and the tests that need it are skipped.
5. `benchmarks/extract_engines.md`: how the lead runs the real comparison on the company with the independent
   key — accuracy (`docgrain_eval.record_golden`), unsupported fields (`docgrain-eval support`), stability
   (`docgrain-eval stability`), coverage, known conflicts kept as `needs_review`, calls/tokens/time.

## Rules

- Do not delete our extractor in this WP. Grep before you import any docling-graph name; list what you could
  not verify. Tests use fake LLM transports (no network). Source text is untrusted data (decision 6).

## Acceptance criteria

- [ ] The `verify.py` move is behaviour-neutral (existing tests green, only import edits).
- [ ] With a fake model, the docling-graph engine produces an `ExtractionResult` whose fields all pass
      `verify.py`; a field whose quote is not in the source is rejected.
- [ ] `--engine docgrain` output is unchanged.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean.
- [ ] Report (Turkish): exact benchmark commands, unverified docling-graph behaviours, risks.
