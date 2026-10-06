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
# Bash reads a script while running it; run from a private copy so the lead can edit the team
# scripts while agents are working.
if [[ -z "${TEAM_SCRIPT_DIR:-}" ]]; then
  export TEAM_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  copy="$(mktemp)"
  cp "$0" "$copy"
  exec bash "$copy" "$@"
fi
source "$TEAM_SCRIPT_DIR/lib.sh"

wp="${1:?usage: run-wp.sh <wp-id> [base-ref]}"
base="${2:-origin/dev}"
spec="$root/docs/plan/wp/$wp.md"
[[ -f "$spec" ]] || { echo "missing WP spec: $spec" >&2; exit 1; }
agent="$(board agent "$wp" 2>/dev/null || true)"
read -r model effort tier engine < <(board model "$wp" | tr -d '\r')

if [[ "${WP_IN_PLACE:-0}" == "1" ]]; then
  workdir="$root"
else
  workdir="$(dirname "$root")/docgrain-wt/$wp"
  if [[ ! -d "$workdir" ]]; then
    git -C "$root" fetch -q origin
    git -C "$root" worktree add -b "codex/$wp" "$workdir" "$base"
  fi
fi

# Agents cannot install packages (sandbox, no network): link the main checkout's node_modules
# into the worktree so type checks and builds work. Junctions need no admin rights on Windows.
link_node_modules() {
  local src rel
  while IFS= read -r src; do
    rel="${src#"$root"/}"
    [[ -e "$workdir/$rel" || ! -d "$workdir/$(dirname "$rel")" ]] && continue
    if command -v cygpath >/dev/null 2>&1; then
      cmd //c mklink //J "$(cygpath -w "$workdir/$rel")" "$(cygpath -w "$src")" >/dev/null
    else
      ln -s "$src" "$workdir/$rel"
    fi
  done < <(find "$root" -maxdepth 3 -type d -name node_modules -not -path "*/node_modules/*" 2>/dev/null)
}
[[ "${WP_IN_PLACE:-0}" == "1" ]] || link_node_modules

run="${WP_RESUME_RUN:-$root/.lead/runs/$wp/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$run"
[[ -n "${WP_RESUME_RUN:-}" ]] || cp "$spec" "$run/spec.md"
printf '%s\n' "$workdir" >"$run/workdir"
[[ -n "${WP_RESUME_RUN:-}" ]] || printf '%s %s %s\n' "$model" "$effort" "$tier" >"$run/model"
echo running >"$run/status"
board step "$wp" working

prompt="You are ${agent:-a member} of the Docgrain team, working on work package $wp.
Claude Code is the tech lead and reviews your work. Read AGENTS.md and docs/plan/ROADMAP.md, then do
the work package below. Work only inside $workdir. Do not commit; the lead commits after review.
Write short progress messages in Turkish at each milestone. Finish with the report format from
AGENTS.md.

----- WORK PACKAGE -----
$(cat "$spec")"

echo "agent: ${agent:-?}  wp: $wp  model: $model/$effort ($tier)  dir: $workdir  logs: $run"
status=0
if [[ -n "${WP_RESUME_RUN:-}" ]]; then
  status=1
else
  if [[ "$engine" == "agy" ]]; then
    run_agy "$wp" "$run" "$workdir" "$prompt" || status=$?
  else
    run_codex "$wp" "$run" "$workdir" -s workspace-write -m "$model" -c "model_reasoning_effort=\"$effort\"" --json -o "$run/report.md" "$prompt" || status=$?
  fi
fi

max_attempts="${WP_ATTEMPTS:-4}"
attempt=1
while [[ $status -ne 0 && $attempt -lt $max_attempts ]] && is_transient_failure "$run"; do
  # Check if it's a quota failure
  resume_at=""
  if grep '"type":"turn.failed"' "$run/events.jsonl" | tail -1 | grep -qEi 'usage limit|try again at'; then
    resume_at="$(grep '"type":"turn.failed"' "$run/events.jsonl" | tail -1 | grep -oEi 'try again at [^"]+' || echo 'later')"
  elif grep '"event":"result"' "$run/events.jsonl" | tail -1 | grep -qEi 'usage limit|try again at|quota|exhausted|429'; then
    resume_at="$(grep '"event":"result"' "$run/events.jsonl" | tail -1 | grep -oEi 'try again at [^"]+' || echo 'later')"
  fi

  if [[ -n "$resume_at" ]]; then
    # It's a quota failure
    echo "paused" >"$run/status"
    echo "$resume_at" >"$run/resume_at"
    
    # Check failover
    target_engine=""
    if [[ "$engine" == "codex" && "${CREW_FAILOVER:-}" == "agy" ]]; then
      target_engine="agy"
    elif [[ "$engine" == "agy" && "${CREW_FAILOVER:-}" == "codex" ]]; then
      target_engine="codex"
    fi
    
    if [[ -n "$target_engine" ]]; then
      # Handover prompt
      printf -v handoff_prompt 'The previous engine hit a quota limit. Continue this work package in the same worktree; do not commit.\n\nSpec:\n%s\n\nGit status:\n%s\n\nGit diff (first 400 lines):\n%s' \
        "$(cat "$spec")" "$(git -C "$workdir" status --short)" "$(git -C "$workdir" diff | head -400)"
      # The run's model file must name the new engine's model before run_agy/run_codex read it.
      read -r model effort tier _ < <(CREW_ENGINE_FORCE="$target_engine" board model "$wp" | tr -d '\r')
      printf '%s %s %s\n' "$model" "$effort" "$tier" >"$run/model"
      
      echo "failover to $target_engine"
      engine="$target_engine"
      echo running >"$run/status"
      status=0
      if [[ "$engine" == "agy" ]]; then
        run_agy "$wp" "$run" "$workdir" "$handoff_prompt" || status=$?
      else
        run_codex "$wp" "$run" "$workdir" -s workspace-write -m "$model" -c "model_reasoning_effort=\"$effort\"" --json -o "$run/report.md" "$handoff_prompt" || status=$?
      fi
      continue
    else
      # No failover, just pause
      echo "exit=$status (paused: $resume_at)"
      exit $status
    fi
  fi

  attempt=$((attempt + 1))
  echo "retry $attempt/$max_attempts after transient failure"
  echo "retry $attempt" >"$run/status"
  [[ -n "${WP_RESUME_RUN:-}" && $attempt -eq 2 ]] || sleep $((60 * (attempt - 1)))
  status=0
  if [[ "$engine" == "agy" && -z "$(tr -d '[:space:]' < "$run/thread" 2>/dev/null)" ]]; then
    # The provider failed before a conversation existed: start the work package again.
    run_agy "$wp" "$run" "$workdir" "$prompt" || status=$?
  elif [[ "$engine" == "agy" ]]; then
    resume_agy "$wp" "$run" "$workdir" "The previous turn stopped because of a transient provider error. Continue the work package from where you left off; check git status first." || status=$?
  else
    resume_codex "$wp" "$run" "$workdir" \
      "The previous turn stopped because of a transient provider error. Continue the work package from where you left off; check git status first." \
      || status=$?
  fi
done

finish_run "$wp" "$run" "$status"
echo "exit=$status report=$run/report.md"
exit $status
