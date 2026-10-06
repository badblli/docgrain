#!/usr/bin/env bash
# Lead → agent: send review feedback or a question to the agent of a WP and let it continue.
#
#   scripts/team/tell.sh <wp-id> "<message>"
#
# Resumes the agent's Codex thread from the latest run (same worktree, same sandbox), logs both
# sides in .lead/chat/<wp-id>.jsonl and moves the WP to "working", then "reported".
set -euo pipefail
# Bash reads a script while running it; run from a private copy so the lead can edit the team
# scripts while agents are working.
if [[ -z "${TEAM_SCRIPT_DIR:-}" ]]; then
  export TEAM_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  copy="$(mktemp)"
  cp "$0" "$copy"
  exec bash "$copy" "$@"
fi
source "$TEAM_SCRIPT_DIR/lib.sh"

wp="${1:?usage: tell.sh <wp-id> \"<message>\"}"
message="${2:?message required}"
run="$(ls -d "$root/.lead/runs/$wp"/2*/ 2>/dev/null | tail -1)"
run="${run%/}"
[[ -n "$run" ]] || { echo "no run for $wp; start it with run-wp.sh" >&2; exit 1; }
workdir="$(cat "$run/workdir")"

board say "$wp" claude "$message"
board step "$wp" working
echo running >"$run/status"

status=0
read -r model effort tier engine < <(board model "$wp" | tr -d '\r')
if [[ "$engine" == "agy" ]]; then
  resume_agy "$wp" "$run" "$workdir" "Message from the tech lead (Claude): $message

Act on it inside this work package, do not commit, then finish with the report format from AGENTS.md." \
    || status=$?
else
  resume_codex "$wp" "$run" "$workdir" "Message from the tech lead (Claude): $message

Act on it inside this work package, do not commit, then finish with the report format from AGENTS.md." \
    || status=$?
fi
if [[ $status -ne 0 ]] && is_transient_failure "$run"; then
  sleep 60
  status=0
  if [[ "$engine" == "agy" ]]; then
    resume_agy "$wp" "$run" "$workdir" "Continue acting on the lead's last message; check git status first." || status=$?
  else
    resume_codex "$wp" "$run" "$workdir" "Continue acting on the lead's last message; check git status first." || status=$?
  fi
fi
finish_run "$wp" "$run" "$status"
exit $status
