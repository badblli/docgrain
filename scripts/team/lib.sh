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

# run_agy <wp> <run-dir> <workdir> <prompt>
# Streams NDJSON into <run-dir>/events.jsonl, writes the final result.response to report.md, conversation id to thread
run_agy() {
  local wp="$1" run="$2" workdir="$3" prompt="$4"
  local agy_bin="${AGY_BIN:-$LOCALAPPDATA/agy/bin/agy.exe}"
  local rc
  
  read -r model effort tier < "$run/model"
  
  set +e
  (cd "$workdir" && "$agy_bin" -p "$prompt" --output-format stream-json --sandbox --mode accept-edits --print-timeout "${AGY_TIMEOUT:-55m}" --model "$model" --effort "$effort") 2>>"$run/stderr.log" \
    | board ingest "$wp" >>"$run/events.jsonl"
  rc=${PIPESTATUS[0]}
  set -e
  
  # Extract thread ID and report from events.jsonl
  # Find the init event or result event for conversation_id
  grep '"conversation_id"' "$run/events.jsonl" | head -1 | grep -o '"conversation_id":"[^"]*"' | cut -d'"' -f4 > "$run/thread" || true
  
  # Extract final response from result event
  grep '"event":"result"' "$run/events.jsonl" | tail -1 | python -c '
import sys, json
try:
    res = json.loads(sys.stdin.read()).get("result", {})
    if "response" in res:
        print(res["response"])
except:
    pass
' > "$run/report.md" || true

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

# resume_agy <wp> <run-dir> <workdir> <message>
resume_agy() {
  local wp="$1" run="$2" workdir="$3" message="$4" thread
  thread="$(cat "$run/thread" 2>/dev/null || true)"
  [[ -n "$thread" ]] || { echo "no thread id in $run/thread" >&2; return 1; }
  
  local agy_bin="${AGY_BIN:-$LOCALAPPDATA/agy/bin/agy.exe}"
  local rc
  
  read -r model effort tier < "$run/model"
  
  set +e
  (cd "$workdir" && "$agy_bin" -p "$message" --conversation "$thread" --output-format stream-json --sandbox --mode accept-edits --print-timeout "${AGY_TIMEOUT:-55m}" --model "$model" --effort "$effort") 2>>"$run/stderr.log" \
    | board ingest "$wp" >>"$run/events.jsonl"
  rc=${PIPESTATUS[0]}
  set -e
  
  grep '"event":"result"' "$run/events.jsonl" | tail -1 | python -c '
import sys, json
try:
    res = json.loads(sys.stdin.read()).get("result", {})
    if "response" in res:
        print(res["response"])
except:
    pass
' > "$run/report.md" || true

  return "$rc"
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
