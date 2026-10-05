"""Team board and lead↔agent conversation log for the Docgrain Codex team.

State lives in .lead/ (ignored by Git) and is shown by the `codex-team` Claude Code mod:
  .lead/board.json        phase, focus and per-WP {agent, step, note}
  .lead/chat/<wp>.jsonl   conversation: {ts, from, kind, text}; from = "claude" or an agent id

Usage:
  board.py phase "<phase>" "<focus>"
  board.py assign <wp> <agent-id>             lead assigns a WP (logs the assignment)
  board.py step <wp> <step> ["<note>"]        move a WP to a step; a note is logged as a lead message
  board.py say <wp> <from> "<text>"           log one message
  board.py agent <wp>                         print the assigned agent id
  board.py model <wp>                         print "<model> <effort> <tier>" from the WP's "- Model:" line
  board.py ingest <wp>                        read Codex --json events on stdin, log agent messages
  board.py report <wp> <report.md>            log the agent's final report summary
  board.py decide "<question>" "<label>|<detail>" ...   ask the user (band above the prompt)
  board.py decide --clear                     remove the pending decision
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEAD = ROOT / ".lead"
BOARD = LEAD / "board.json"
TEAM = json.loads((ROOT / "docs/plan/team.json").read_text(encoding="utf-8"))
STEPS = [s["id"] for s in TEAM["steps"]]
AGENTS = {a["id"] for a in TEAM["agents"]}


def _load() -> dict:
    try:
        return json.loads(BOARD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "", "focus": "", "items": {}}


def _save(board: dict) -> None:
    LEAD.mkdir(exist_ok=True)
    tmp = BOARD.with_suffix(".tmp")
    tmp.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(BOARD)


def say(wp: str, sender: str, text: str, kind: str = "message") -> None:
    text = text.strip()
    if not text:
        return
    chat = LEAD / "chat"
    chat.mkdir(parents=True, exist_ok=True)
    entry = {"ts": int(time.time() * 1000), "from": sender, "kind": kind, "text": text}
    with (chat / f"{wp}.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(entry, ensure_ascii=False) + "\n")


def agent_of(wp: str) -> str:
    return _load()["items"].get(wp, {}).get("agent", "")


def step(wp: str, step_id: str, note: str = "") -> None:
    if step_id not in STEPS and step_id != "failed":
        raise SystemExit(f"unknown step {step_id}; one of {STEPS + ['failed']}")
    board = _load()
    item = board["items"].setdefault(wp, {})
    item["step"] = step_id
    if note:
        item["note"] = note
        say(wp, "claude", note, "note")
    _save(board)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    cmd, args = argv[1], argv[2:]
    if cmd == "phase":
        board = _load()
        board["phase"], board["focus"] = args[0], args[1] if len(args) > 1 else ""
        _save(board)
    elif cmd == "assign":
        wp, agent = args
        if agent not in AGENTS:
            raise SystemExit(f"unknown agent {agent}; one of {sorted(AGENTS)}")
        board = _load()
        board["items"].setdefault(wp, {})["agent"] = agent
        _save(board)
        spec = (ROOT / "docs/plan/wp" / f"{wp}.md").read_text(encoding="utf-8")
        summary = next((ln.split(":", 1)[1].strip() for ln in spec.splitlines() if ln.startswith("- Özet:")), wp)
        say(wp, "claude", f"Görev: {summary}", "assign")
        step(wp, "assigned")
    elif cmd == "step":
        step(args[0], args[1], args[2] if len(args) > 2 else "")
    elif cmd == "model":
        routing = json.loads((ROOT / "docs/plan/models.json").read_text(encoding="utf-8"))
        spec = (ROOT / "docs/plan/wp" / f"{args[0]}.md").read_text(encoding="utf-8")
        tier = next((ln.split(":", 1)[1].strip().split()[0].lower() for ln in spec.splitlines()
                     if ln.startswith("- Model:")), routing["default"])
        if tier not in routing["tiers"]:
            raise SystemExit(f"unknown model tier {tier}; one of {sorted(routing['tiers'])}")
        print(routing["tiers"][tier]["model"], routing["tiers"][tier]["effort"], tier)
    elif cmd == "agent":
        print(agent_of(args[0]))
    elif cmd == "say":
        say(args[0], args[1], args[2])
    elif cmd == "ingest":
        wp = args[0]
        sender = agent_of(wp) or "codex"
        for line in sys.stdin:
            sys.stdout.write(line)
            sys.stdout.flush()
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                say(wp, sender, item.get("text", ""))
            elif event.get("type") == "turn.failed":
                say(wp, sender, "Hata: " + str((event.get("error") or {}).get("message", "")), "error")
    elif cmd == "decide":
        path = LEAD / "decision.json"
        if args == ["--clear"]:
            path.unlink(missing_ok=True)
            return
        options = []
        for raw in args[1:]:
            label, _, detail = raw.partition("|")
            options.append({"label": label.strip(), "detail": detail.strip()})
        decision = {"id": str(int(time.time() * 1000)), "question": args[0], "options": options, "status": "open"}
        LEAD.mkdir(exist_ok=True)
        path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    elif cmd == "report":
        wp, path = args
        text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        summary = text.split("## Summary", 1)[-1].split("\n## ", 1)[0].strip() if "## Summary" in text else text[:600]
        say(wp, agent_of(wp) or "codex", "Rapor: " + summary, "report")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    main(sys.argv)
