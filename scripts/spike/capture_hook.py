"""M0 spike: record exactly what Claude Code sends to a command hook.

Usage (from .claude/settings.local.json):
    <python> scripts/spike/capture_hook.py <EventName>

Writes one JSON file per invocation to docs/spike/payloads/raw/ (gitignored).
Prints nothing and always exits 0, so it never makes a decision for Claude Code.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

T0 = time.perf_counter()

ENV_KEYS_EXACT = {
    "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "TERM", "TMUX", "TMUX_PANE", "WT_SESSION",
    "VSCODE_PID", "VSCODE_IPC_HOOK_CLI", "VSCODE_GIT_IPC_HANDLE", "CURSOR_TRACE_ID",
    "SHELL", "COMSPEC", "MSYSTEM", "SSH_CONNECTION", "SESSIONNAME",
}
ENV_KEY_PARTS = ("CLAUDE", "ORCA", "OPENBOT", "ANTHROPIC")
SECRET_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")


def selected_env() -> dict[str, str]:
    out = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if ku in ENV_KEYS_EXACT or any(p in ku for p in ENV_KEY_PARTS):
            out[k] = "<redacted>" if any(s in ku for s in SECRET_PARTS) else v
    return dict(sorted(out.items()))


def parent_chain() -> list[dict]:
    try:
        import psutil
    except ImportError:
        return [{"error": "psutil not installed"}]
    chain = []
    try:
        proc = psutil.Process().parent()
        while proc is not None and len(chain) < 15:
            item: dict = {"pid": proc.pid}
            for attr in ("name", "exe", "cmdline"):
                try:
                    item[attr] = getattr(proc, attr)()
                except (psutil.AccessDenied, psutil.ZombieProcess, OSError) as e:
                    item[attr] = None
                    item.setdefault("errors", []).append(f"{attr}: {type(e).__name__}")
            chain.append(item)
            proc = proc.parent()
    except psutil.Error as e:
        chain.append({"error": type(e).__name__})
    return chain


def main() -> None:
    try:
        event = sys.argv[1] if len(sys.argv) > 1 else "unknown"
        raw = sys.stdin.buffer.read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            payload = {"_unparsed": raw.decode("utf-8", "replace")}
        t_read = time.perf_counter()
        record = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "event_arg": event,
            "stdin": payload,
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "platform": sys.platform,
            "python": sys.executable,
            "env": selected_env(),
            "parent_chain": parent_chain(),
        }
        record["timing_ms"] = {
            "stdin_read": round((t_read - T0) * 1000, 1),
            "total": round((time.perf_counter() - T0) * 1000, 1),
        }
        out_dir = Path(__file__).resolve().parents[2] / "docs" / "spike" / "payloads" / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S_%f")
        (out_dir / f"{stamp}_{event}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # never let the spike affect Claude Code
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
