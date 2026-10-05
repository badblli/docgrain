#!/usr/bin/env bash
# Run one work package with its assigned Codex agent in its own git worktree.
#
#   scripts/team/board.py assign <wp-id> <agent-id>    # first: who does it (docs/plan/team.json)
#   scripts/team/run-wp.sh <wp-id> [base-ref]          # new worktree ../docgrain-wt/<wp-id>
#   WP_IN_PLACE=1 scripts/team/run-wp.sh <wp-id>       # use the current checkout instead
#   WP_RESUME_RUN=<run dir> scripts/team/run-wp.sh <wp-id>   # continue a transiently failed run
#
# Logs: .lead/runs/<wp-id>/<timestamp>/ (events.jsonl, report.md, status); conversation:
# .lead/chat/<wp-id>.jsonl. Lead feedback to a running/finished agent: scripts/team/tell.sh.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

wp="${1:?usage: run-wp.sh <wp-id> [base-ref]}"
base="${2:-origin/dev}"
spec="$root/docs/plan/wp/$wp.md"
[[ -f "$spec" ]] || { echo "missing WP spec: $spec" >&2; exit 1; }
agent="$(board agent "$wp" 2>/dev/null || true)"

if [[ "${WP_IN_PLACE:-0}" == "1" ]]; then
  workdir="$root"
else
  workdir="$(dirname "$root")/docgrain-wt/$wp"
  if [[ ! -d "$workdir" ]]; then
    git -C "$root" fetch -q origin
    git -C "$root" worktree add -b "codex/$wp" "$workdir" "$base"
  fi
fi

run="${WP_RESUME_RUN:-$root/.lead/runs/$wp/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$run"
[[ -n "${WP_RESUME_RUN:-}" ]] || cp "$spec" "$run/spec.md"
printf '%s\n' "$workdir" >"$run/workdir"
echo running >"$run/status"
board step "$wp" working

prompt="You are ${agent:-a member} of the Docgrain team, working on work package $wp.
Claude Code is the tech lead and reviews your work. Read AGENTS.md and docs/plan/ROADMAP.md, then do
the work package below. Work only inside $workdir. Do not commit; the lead commits after review.
Write short progress messages in Turkish at each milestone. Finish with the report format from
AGENTS.md.

----- WORK PACKAGE -----
$(cat "$spec")"

echo "agent: ${agent:-?}  wp: $wp  dir: $workdir  logs: $run"
status=0
if [[ -n "${WP_RESUME_RUN:-}" ]]; then
  status=1
else
  run_codex "$wp" "$run" "$workdir" -s workspace-write --json -o "$run/report.md" "$prompt" || status=$?
fi

max_attempts="${WP_ATTEMPTS:-4}"
attempt=1
while [[ $status -ne 0 && $attempt -lt $max_attempts ]] && is_transient_failure "$run"; do
  attempt=$((attempt + 1))
  echo "retry $attempt/$max_attempts after transient failure"
  echo "retry $attempt" >"$run/status"
  [[ -n "${WP_RESUME_RUN:-}" && $attempt -eq 2 ]] || sleep $((60 * (attempt - 1)))
  status=0
  resume_codex "$wp" "$run" "$workdir" \
    "The previous turn stopped because of a transient provider error. Continue the work package from where you left off; check git status first." \
    || status=$?
done

finish_run "$wp" "$run" "$status"
echo "exit=$status report=$run/report.md"
exit $status
