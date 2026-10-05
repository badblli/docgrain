# wp13-eval-context-source — Measure with the compact context too

- Özet: Ölçüm aracı bağlamı eski canonical.md yerine yeni kompakt context.md ile de kurabilsin; yayında context.md yoksa revision'dan yerelde üretsin.
- Model: hafif
- Phase: D1
- Branch: `codex/wp13-eval-context-source` (base: `origin/dev`)
- Depends on: wp12, wp21 (both merged)
- Role: implementer

## Goal

`docgrain-eval run` always builds the direct context from the published `canonical.md`. Existing
revisions were published before `context.md` existed, so we cannot compare the two formats. Add a
switch so the same questions can be asked with either context.

## Tasks

1. `docgrain-eval run --context {canonical,compact}` (default `canonical`, unchanged behavior).
2. `compact`: per document, fetch the published `context.md`; if the publication has no such file
   (404), fetch the revision snapshot (`GET /v1/documents/{id}/knowledge` → `snapshot`) and build it
   locally with `docgrain_domain.canonical.ai_output.project_ai` + `context_projection` (chunks via
   `derive_chunk_set(snapshot, ChunkingSpec())`). Record per document which source was used.
3. `summary.json` / `summary.md` include `context_mode` and the per-document source.
4. Unit tests with a fake transport for: published context.md used; 404 → local projection; default
   mode unchanged.

## Acceptance criteria

- [ ] `--dry-run --context compact` against the live API prints a context size near 128k characters.
- [ ] Existing eval tests unchanged and passing; new tests pass; Ruff clean (repo venv).
