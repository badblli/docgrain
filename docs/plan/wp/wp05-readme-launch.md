# wp05-readme-launch — English-first README for the open-source launch

- Özet: Açık kaynak lansmanı için README'yi İngilizce, dikkat çekici ve dürüst hâle getir; Türkçesini README.tr.md'ye taşı. Müşteri veya iş ortağı adı yok.
- Model: standart
- Phase: D0
- Branch: `codex/wp02-readme` (update the existing branch/PR badblli/docgrain#10)
- Depends on: wp02
- Role: scribe (Chatot)

## Goal

The repo will be announced on X/Twitter to get stars. Visitors are international developers who
decide in ~10 seconds. The README must make them understand the problem, see why Docgrain is
different, trust that it is honest, and run it — without naming any customer or partner.

## Structure (README.md, English)

1. Name + one-line tagline (e.g. "Turn messy company documents into versioned, source-linked
   knowledge your AI, apps and website can trust."). Badges: CI (GitHub Actions `Quality`
   workflow on `dev`), license MIT, status pre-alpha, Python 3.12.
2. **Why** — 3 short bullets on the problem (PDF/Excel/Word chaos, RAG hallucinations without
   provenance, re-processing whole docs for a one-word change).
3. **What it does** — the four goals with honest markers (✅ works today / 🚧 in progress / 🗺 planned).
4. **How it works** — the ASCII flow diagram.
5. **Quick start** — Compose stack + demo mode (same verified commands as today).
6. **Measured, not claimed** — `docgrain-eval`: golden questions, abstention, citations; numbers
   are published per release (no numbers yet: say "first baseline coming").
7. **Built by an AI team** — short, fun: Claude Code as tech lead, Codex agents with Pokémon names
   working in parallel worktrees, every change reviewed and measured (`AGENTS.md`, `scripts/team/`).
   This is a genuine differentiator; keep it to ~6 lines.
8. **Roadmap** — the D1–D7 phases in one line each (from `docs/plan/ROADMAP.md`).
9. **Contributing**, **License**. Link `README.tr.md` ("Türkçe") at the top.

`README.tr.md`: the current Turkish README content, updated to match the same structure.

## Rules

- No customer, hotel, partner-product or real document names anywhere (term list: `C:/Users/root/Documents/projects/docgrain/.lead/scrub-terms.txt`, never copy it into a file). Use "a hotel" or "a company".
- Honest: nothing marked ✅ that is not verified in code. Pre-alpha stated clearly.
- No fake stars/numbers/testimonials. ≤ ~180 lines each.
- Only README.md and README.tr.md change.

## Acceptance criteria

- [ ] `git grep -i -E "$(cat C:/Users/root/Documents/projects/docgrain/.lead/scrub-terms.txt)"` on both files: empty.
- [ ] Every command and link exists in the repo.
- [ ] First screen answers: what, why, does it work yet, how to try it.
