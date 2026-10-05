#!/usr/bin/env bash
# Lead → agent: send review feedback or a question to the agent of a WP and let it continue.
#
#   scripts/team/tell.sh <wp-id> "<message>"
#
# Resumes the agent's Codex thread from the latest run (same worktree, same sandbox), logs both
# sides in .lead/chat/<wp-id>.jsonl and moves the WP to "working", then "reported".
set -euo pipefail
source "$(dirname "$0")/lib.sh"

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
resume_codex "$wp" "$run" "$workdir" "Message from the tech lead (Claude): $message

Act on it inside this work package, do not commit, then finish with the report format from AGENTS.md." \
  || status=$?
if [[ $status -ne 0 ]] && is_transient_failure "$run"; then
  sleep 60
  status=0
  resume_codex "$wp" "$run" "$workdir" "Continue acting on the lead's last message; check git status first." || status=$?
fi
finish_run "$wp" "$run" "$status"
exit $status
