# wp02-readme — README that says what Docgrain is and where it stands

- Özet: README'yi baştan yaz: Docgrain ne yapar, kime yarar, bugün ne çalışıyor ne çalışmıyor, nasıl çalıştırılır, ekip nasıl çalışır.
- Model: standart
- Phase: D0
- Branch: `codex/wp02-readme` (worktree `C:/Users/root/Documents/projects/docgrain-wt/wp02-readme`, base `origin/dev`)
- Depends on: none
- Role: scribe (Chatot)

## Goal

The repository is public and its README is a dense changelog of internal milestones (M0–M2g,
N1–N3) that a newcomer cannot follow. Rewrite it so a visitor understands the product in one
minute and a developer can run it in five.

## Audience and language

Turkish (the team's language), with a two-sentence English summary at the very top for GitHub
visitors. Plain words; technical terms only where a developer needs them. Use the glossary in
`docs/plan/ROADMAP.md`.

## Content (in this order)

1. Title + English summary (2 sentences) + Turkish one-liner.
2. **Ne yapar?** The four product promises from `docs/plan/ROADMAP.md` (normalize every format into
   one canonical model; versioning without reprocessing; collections as a shared data pool for AI,
   mobile, web; model-agnostic fast answers, embeddings optional). A small text diagram of the flow.
3. **Bugün durum** — honest status table: what works today (six formats ingested, canonical model,
   source-side-by-side review and immutable revisions, published JSON/Markdown/ZIP, `docgrain-eval`
   measurement) vs. not yet (tables in some PDFs, file-version upload, collections extraction,
   access API for apps, model-agnostic AI access, auth). Pre-alpha. Link `docs/plan/ROADMAP.md`.
4. **Hızlı başlangıç** — Docker Compose live stack (keep the commands and ports that exist in the
   current README and `docker-compose.yml`; verify them by reading the files, do not invent), demo
   mode, tests (`python -m pytest -q`, `ruff check …`, web build).
5. **Ölçüm** — one short section on `docgrain-eval` (see `docs/plan/eval.md`) and that golden data
   stays out of Git.
6. **Nasıl geliştiriyoruz** — Claude Code as tech lead, named Codex agents per work package
   (`AGENTS.md`, `docs/plan/wp/`, `scripts/team/`), every change reviewed and measured.
7. **Mimari ve kararlar** — short pointers: `docs/ARCHITECTURE.md`, `docs/adr/`, older milestone
   docs in `docs/` as history.
8. License.

## Rules

- Do not include any customer content (hotel names, document names, prices, quotes, real file
  names). The repo is public. Use generic examples ("bir otelin fact sheet'i").
- Do not claim anything you have not verified in the code or docs. When unsure, leave it out.
- Keep it under ~170 lines. Move nothing else; only `README.md` changes.

## Acceptance criteria

- [ ] A newcomer can answer "what is it, does it work yet, how do I run it" from the first screen
      and the quick-start section.
- [ ] Every command in the README exists in the repo (Makefile, compose, package scripts).
- [ ] No customer content; `grep -i -E "dobedan|corendon"` on README is empty.
