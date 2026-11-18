"""Claude Code hook payload -> SeKantor event v1 (as a plain dict; stdlib only, the hook imports this).

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

WAITING_INPUT_NOTIFICATIONS = {"agent_needs_input", "elicitation_dialog", "elicitation_url_dialog"}


def new_event_id() -> str:
    """Time-sortable, unique: 16 hex chars of nanoseconds + 8 random hex chars."""
    return f"{time.time_ns():016x}{secrets.token_hex(4)}"


ACTIVITY_KINDS = {
    "Read": "read", "Grep": "read", "Glob": "read", "LS": "read", "NotebookRead": "read",
    "Edit": "edit", "MultiEdit": "edit", "Write": "edit", "NotebookEdit": "edit",
    "Bash": "run", "BashOutput": "run", "KillShell": "run", "PowerShell": "run",
    "WebSearch": "web", "WebFetch": "web",
}


def activity_kind(tool: str) -> str:
    """The kind of work a tool does; a tool never seen before (MCP, subagent) is ``other``."""
    return ACTIVITY_KINDS.get(str(tool), "other")


def _clip(text: str | None, n: int) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split()) if n <= SUMMARY_MAX else str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def tool_input_text(tool_input) -> str | None:
    """The one line a person needs to judge a tool call."""
    if not isinstance(tool_input, dict):
        return _clip(tool_input, INPUT_MAX) if tool_input else None
    for key in ("command", "file_path", "url", "pattern", "query", "prompt", "description"):
        if tool_input.get(key):
            return _clip(tool_input[key], INPUT_MAX)
    return _clip(json.dumps(tool_input, ensure_ascii=False, separators=(",", ":")), INPUT_MAX)


def question_text(tool_input) -> str:
    """'Asks: <first question> (option, option)' from AskUserQuestion's input."""
    try:
        q = (tool_input or {}).get("questions", [])[0]
    except (AttributeError, IndexError, TypeError):
        return "Asks you a question"
    labels = ", ".join(o.get("label", "") for o in q.get("options") or [] if isinstance(o, dict))
    text = q.get("question") or q.get("header") or "a question"
    return f"Asks: {text}" + (f" ({labels})" if labels else "")


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


def translate(payload: dict) -> dict | None:
    name = payload.get("hook_event_name")
    sid = payload.get("session_id")
    if not name or not sid:
        return None

    event_id = new_event_id()
    status: str | None = None
    etype = "status_changed"
    summary: str | None = None
    request: dict | None = None
    activity: dict | None = None
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
            # Claude Code woke the agent on its own (a hook or background task finished)
            summary = "Woken by a hook"
        else:
            summary = _clip(prompt, SUMMARY_MAX)
    elif name == "PreToolUse":
        status = "running"
        text = tool_input_text(payload.get("tool_input"))
        summary = _clip(f"{tool}: {text}" if text else tool, SUMMARY_MAX)
        if tool:
            activity = {"tool": str(tool)[:100], "kind": activity_kind(tool)}
    elif name == "PermissionRequest" and tool == "AskUserQuestion":
        # Claude asks the person something. Approving the tool does not answer it, so this is a
        # question to answer in the app, not an approval (dogfooding 2026-11-11).
        status = "waiting_input"
        request = {"kind": "question", "tool": tool}
        summary = _clip(question_text(payload.get("tool_input")), SUMMARY_MAX)
    elif name == "PermissionRequest":
        status = "waiting_approval"
        text = tool_input_text(payload.get("tool_input"))
        request = {"kind": "tool", "tool": tool, "input": text}
        summary = _clip(f"Wants to run: {text}" if text else f"Wants to use {tool}", SUMMARY_MAX)
    elif name in ("PostToolUse", "PostToolUseFailure", "PermissionDenied"):
        status = "running"
    elif name == "Notification":
        kind = payload.get("notification_type")
        if kind == "permission_prompt":
            status = "waiting_approval"
        elif kind in WAITING_INPUT_NOTIFICATIONS:
            status = "waiting_input"
            request = {"kind": "question"}
            summary = _clip(payload.get("message"), SUMMARY_MAX)
        else:
            etype = "message"
            if kind != "idle_prompt":
                summary = _clip(payload.get("message"), SUMMARY_MAX)
    elif name == "Stop":
        status = "reported"
        summary = _clip(payload.get("last_assistant_message"), SUMMARY_MAX)
        request = {"kind": "report"}
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
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "session_id": f"claude:{sid}",
        "agent": {"name": "claude", "model": payload.get("model")},
        "workspace": {"cwd": cwd, "branch": git_branch(cwd)},
        "type": etype,
        "status": status,
        "summary": summary,
        "request": request,
        "activity": activity,
    }
    return {k: v for k, v in event.items() if v is not None}
