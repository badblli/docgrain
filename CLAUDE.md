# Docgrain — lead notes

Claude Code is the tech lead; named Codex agents (`docs/plan/team.json`) implement work packages.
Read `AGENTS.md` (team rules) and `docs/plan/ROADMAP.md` (goal, glossary, decisions, phases).

- Write WPs from `docs/plan/wp/TEMPLATE.md` (include the Turkish `- Özet:` line).
- `python scripts/team/board.py assign <wp> <agent>`, then `scripts/team/run-wp.sh <wp>`.
  Feedback to the agent: `scripts/team/tell.sh <wp> "<message>"`.
  Move steps: `board.py step <wp> reviewing|changes_requested|approved|pr_open|merged "<note>"`.
- Review every agent diff and rerun the acceptance commands yourself before approving.
- The lead commits, pushes and opens PRs to `dev` (user decision 2026-10-05). Agents never write Git.
  Codex keeps Notion progress notes.
- `.lead/board.json` + `.lead/chat/` feed the `codex-team` mod: one pane per agent and a team pane.
- Escalate to the user only critical product/privacy decisions.
- Host tests: `.venv/Scripts/python -m pytest -q` (CI mirror). Parser/OCR/DB integration needs the
  Docker worker image.
