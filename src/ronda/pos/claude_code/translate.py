"""Claude Code hook payload -> Ronda event v1 (as a plain dict; stdlib only, the hook imports this).

Mapping per ADR-0002. Returns None for hooks that must not change anything (e.g. SubagentStop).
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone

SOURCE = "claude-code"
SUMMARY_MAX = 300
INPUT_MAX = 4000

WAITING_INPUT_NOTIFICATIONS = {"idle_prompt", "agent_needs_input", "elicitation_dialog", "elicitation_url_dialog"}


def new_event_id() -> str:
    """Time-sortable, unique: 16 hex chars of nanoseconds + 8 random hex chars."""
    return f"{time.time_ns():016x}{secrets.token_hex(4)}"


def _clip(text: str | None, n: int) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split()) if n <= SUMMARY_MAX else str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def tool_input_text(tool: str | None, tool_input) -> str | None:
    """The one line a person needs to judge a tool call."""
    if not isinstance(tool_input, dict):
        return _clip(tool_input, INPUT_MAX) if tool_input else None
    for key in ("command", "file_path", "url", "pattern", "query", "prompt", "description"):
        if tool_input.get(key):
            return _clip(tool_input[key], INPUT_MAX)
    return _clip(json.dumps(tool_input, ensure_ascii=False, separators=(",", ":")), INPUT_MAX)


def git_branch(cwd: str | None) -> str | None:
    """Read the branch from .git/HEAD without running git (worktrees included)."""
    if not cwd:
        return None
    try:
        d = os.path.abspath(cwd)
        for _ in range(40):
            dotgit = os.path.join(d, ".git")
            if os.path.isdir(dotgit):
                head = os.path.join(dotgit, "HEAD")
                break
            if os.path.isfile(dotgit):
                with open(dotgit, encoding="utf-8") as f:
                    line = f.read().strip()
                if line.startswith("gitdir:"):
                    gd = line[7:].strip()
                    head = os.path.join(gd if os.path.isabs(gd) else os.path.join(d, gd), "HEAD")
                    break
                return None
            parent = os.path.dirname(d)
            if parent == d:
                return None
            d = parent
        else:
            return None
        with open(head, encoding="utf-8") as f:
            ref = f.read().strip()
        if ref.startswith("ref: refs/heads/"):
            return ref[len("ref: refs/heads/"):]
        return ref[:12] or None  # detached HEAD: short sha
    except OSError:
        return None


def translate(payload: dict, now: datetime | None = None) -> dict | None:
    name = payload.get("hook_event_name")
    sid = payload.get("session_id")
    if not name or not sid:
        return None

    event_id = new_event_id()
    status: str | None = None
    etype = "status_changed"
    summary: str | None = None
    request: dict | None = None
    tool = payload.get("tool_name")

    if name == "SessionStart":
        etype = "session_started"
        source = payload.get("source")
        status = None if source == "compact" else "waiting_input"
        summary = {"resume": "Resumed", "clear": "Cleared", "fork": "Forked"}.get(source, "Session started")
    elif name == "UserPromptSubmit":
        status = "running"
        prompt = payload.get("prompt") or ""
        if prompt.lstrip().startswith("<task-notification>"):
            # A hook woke the agent (asyncRewake), e.g. a reply sent through Ronda
            summary = "Continuing after your reply" if "Stop hook" in prompt else "Woken by a hook"
        else:
            summary = _clip(prompt, SUMMARY_MAX)
    elif name == "PreToolUse":
        status = "running"
        text = tool_input_text(tool, payload.get("tool_input"))
        summary = _clip(f"{tool}: {text}" if text else tool, SUMMARY_MAX)
    elif name == "PermissionRequest":
        status = "waiting_approval"
        text = tool_input_text(tool, payload.get("tool_input"))
        request = {"kind": "tool", "tool": tool, "input": text, "id": event_id}
        summary = _clip(f"Wants to run: {text}" if text else f"Wants to use {tool}", SUMMARY_MAX)
    elif name in ("PostToolUse", "PostToolUseFailure", "PermissionDenied"):
        status = "running"
    elif name == "Notification":
        kind = payload.get("notification_type")
        if kind == "permission_prompt":
            status = "waiting_approval"
        elif kind in WAITING_INPUT_NOTIFICATIONS:
            status = "waiting_input"
        else:
            etype = "message"
        summary = _clip(payload.get("message"), SUMMARY_MAX) if etype == "message" else None
    elif name == "Stop":
        status = "waiting_input"
        summary = _clip(payload.get("last_assistant_message"), SUMMARY_MAX)
        request = {"kind": "input", "id": event_id}
    elif name == "StopFailure":
        status = "error"
        summary = _clip(f"Error: {payload.get('error') or 'unknown'}", SUMMARY_MAX)
    elif name == "SessionEnd":
        etype = "session_ended"
        status = "ended"
        summary = _clip(f"Ended ({payload.get('reason')})" if payload.get("reason") else "Ended", SUMMARY_MAX)
    else:
        return None  # SubagentStart/Stop and anything else never changes the session

    cwd = payload.get("cwd")
    event = {
        "v": 1,
        "event_id": event_id,
        "ts": (now or datetime.now(timezone.utc)).isoformat(),
        "source": SOURCE,
        "session_id": f"claude:{sid}",
        "agent": {"name": "claude", "model": payload.get("model")},
        "workspace": {"cwd": cwd, "branch": git_branch(cwd)},
        "type": etype,
        "status": status,
        "summary": summary,
        "request": request,
        "capabilities": [],
    }
    return {k: v for k, v in event.items() if v is not None}
