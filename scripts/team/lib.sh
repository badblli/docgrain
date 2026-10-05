# Shared helpers for the team scripts (sourced, not executed).

root="$(git rev-parse --show-toplevel)"
board() { PYTHONUTF8=1 python -u "$root/scripts/team/board.py" "$@"; }

# The global npm `codex` may be too old for the account's models; prefer the desktop app's binary.
codex_bin="${CODEX_BIN:-}"
if [[ -z "$codex_bin" ]]; then
  codex_bin="$(ls -t "$LOCALAPPDATA"/OpenAI/Codex/bin/*/codex.exe 2>/dev/null | head -1 || true)"
  codex_bin="${codex_bin:-codex}"
fi

# run_codex <wp> <run-dir> <workdir> <codex exec args...>
# Streams events into <run-dir>/events.jsonl and the agent's messages into the WP conversation.
run_codex() {
  local wp="$1" run="$2" workdir="$3"
  shift 3
  local rc
  set +e
  (cd "$workdir" && "$codex_bin" exec "$@") 2>>"$run/stderr.log" \
    | board ingest "$wp" >>"$run/events.jsonl"
  rc=${PIPESTATUS[0]}
  set -e
  return "$rc"
}

# Resume the run's Codex thread with a message; retries transient provider errors.
# resume_codex <wp> <run-dir> <workdir> <message>
resume_codex() {
  local wp="$1" run="$2" workdir="$3" message="$4" thread
  thread="$(grep -o '"thread_id":"[^"]*"' "$run/events.jsonl" | head -1 | cut -d'"' -f4)"
  [[ -n "$thread" ]] || { echo "no thread id in $run/events.jsonl" >&2; return 1; }
  run_codex "$wp" "$run" "$workdir" resume "$thread" -c 'sandbox_mode="workspace-write"' --json \
    -o "$run/report.md" "$message"
}

is_transient_failure() {
  grep '"type":"turn.failed"' "$1/events.jsonl" | tail -1 \
    | grep -qE 'capacity|disconnect|timed out|overloaded|rate limit'
}

# finish_run <wp> <run-dir> <status>
finish_run() {
  local wp="$1" run="$2" status="$3"
  if [[ $status -eq 0 ]]; then
    echo done >"$run/status"
    board report "$wp" "$run/report.md"
    board step "$wp" reported
  else
    echo "failed exit=$status" >"$run/status"
    board step "$wp" failed
  fi
}
