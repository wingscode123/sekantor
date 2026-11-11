"""End-to-end check for M1: a real Claude Code session must show up in the inbox within 1 s and move
running -> waiting_input -> ended.

    uv run python scripts/e2e_claude.py           # needs `ronda up` and `ronda install claude --project`

Listens on WS /v1/stream with the local token, runs `claude -p` in this repo, and prints every status
change with its delay from the hook's own timestamp to arrival in the stream.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
HOST_VARS = ("ORCA_", "OPENBOT", "CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_PID", "VSCODE", "TERM_PROGRAM", "TMUX", "WT_SESSION")
PROMPT = "Run `git log --oneline -3` with your shell tool, then answer in one short sentence."


async def main() -> int:
    token = (Path(os.environ.get("RONDA_HOME") or Path.home() / ".ronda") / "token").read_text().strip()
    url = "ws://127.0.0.1:7878/v1/stream"
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}) as ws:
        json.loads(await ws.recv())  # snapshot
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(HOST_VARS)}
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--model", "haiku", "--allowedTools", "Bash(git log *)", "PowerShell(git log *)",
            "--", PROMPT, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        seen: list[tuple[str, float]] = []
        mine: str | None = None
        last = None
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg.get("type") != "session":
                continue
            s, ev = msg["session"], msg.get("event") or {}
            if mine is None and ev.get("type") == "session_started" and (s.get("workspace") or {}).get("cwd", "").lower() == str(ROOT).lower():
                mine = s["session_id"]
            if s["session_id"] != mine:
                continue
            delay = (datetime.now(timezone.utc) - datetime.fromisoformat(ev["ts"])).total_seconds() if ev else 0.0
            if s["status"] != last:
                seen.append((s["status"], delay))
                host = (s.get("host") or {}).get("app")
                print(f"{s['status']:<17} delay {delay * 1000:6.0f} ms   host={host} branch={s['workspace'].get('branch')}")
                last = s["status"]
            if s["status"] == "ended":
                break
        await proc.wait()
    statuses = [st for st, _ in seen]
    worst = max((d for _, d in seen), default=0)
    ok = statuses[:1] == ["waiting_input"] and "running" in statuses and statuses[-1] == "ended" \
        and statuses.index("running") < len(statuses) - 1 and "waiting_input" in statuses[statuses.index("running"):]
    print(f"sequence: {' -> '.join(statuses)}")
    print(f"worst delay: {worst * 1000:.0f} ms  ({'within' if worst < 1 else 'OVER'} 1 s)")
    print("PASS" if ok and worst < 1 else "FAIL")
    return 0 if ok and worst < 1 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
