# wp03-notion-sync — Keep the Notion roadmap page in sync with the team

- Özet: Notion'daki Docgrain yol haritası sayfasına ilerleme günlüğü ekle ve güncel tut (biten iş paketleri, PR'lar, bulgular, açık kararlar).
- Model: hafif
- Phase: D0
- Branch: none (Notion only)
- Depends on: none
- Role: scribe (Chatot)

## Goal

The user follows the project in Notion. The roadmap page
(https://app.notion.com/p/3f073464cac5811fb530e6ee6fa36e26, child of the Docgrain project page)
must show what the team actually did, without the user reading Git or this terminal.

## Sources of truth (read, never invent)

- `.lead/board.json` (phase, focus, per-WP agent/step/note), `.lead/chat/<wp>.jsonl` (lead notes,
  agent reports), `docs/plan/wp/*.md` (Özet lines), `docs/plan/team.json` (agent names: use the
  active theme's names), merged PRs (`gh pr list --state all --limit 20`).

## What to write

1. If missing, add a `## İlerleme günlüğü` section at the end of the roadmap page; newest entry on
   top. One entry per day: date mention, then bullets: finished WPs (agent name, one-line outcome,
   PR link `badblli/docgrain#N`), running WPs, notable findings, open decisions for the user.
2. Update the page's status callout at the top only if the phase changed.
3. Keep entries short (≤ 8 bullets per day). Turkish.

## Rules

- Make the smallest edit: append/insert, never rewrite or delete existing sections.
- Notion is private, but still do not paste raw document text or long quotes.
- Report back: what you changed (section, number of bullets) and the page URL.
