"""Pure logic of the tmux pos: which panes run agents, and what state their screen shows."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

AGENTS = ("claude", "codex", "opencode", "gemini", "aider")
APPROVAL_LINES = 4  # a question must be in the last non-empty lines to count
QUIET_S = 30.0      # without a recognised prompt, a still screen means "waiting" only after this long
LIST_FORMAT = "\t".join(["#{pane_id}", "#{session_name}", "#{window_index}.#{pane_index}", "#{pane_pid}",
                         "#{pane_current_command}", "#{pane_current_path}"])


@dataclass
class Pane:
    pane_id: str        # %12
    session: str        # tmux session name
    index: str          # window.pane
    pid: int            # the pane's shell
    command: str        # what runs in the foreground
    cwd: str


def parse_panes(text: str) -> list[Pane]:
    panes = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        try:
            pid = int(parts[3])
        except ValueError:
            continue
        panes.append(Pane(parts[0], parts[1], parts[2], pid, parts[4], parts[5]))
    return panes


def agent_of(name: str | None, cmdline: list[str] | None) -> str | None:
    """'codex' for a codex binary, or for node/python running a script named after an agent."""
    base = re.sub(r"\.(exe|cmd|js|mjs|py)$", "", (name or "").lower())
    if base in AGENTS:
        return base
    if base in ("node", "bun", "deno", "python", "python3") or base.startswith("python3."):
        for arg in (cmdline or [])[1:4]:
            a = arg.replace("\\", "/").lower()
            for agent in AGENTS:
                if re.search(rf"(^|/|@[\w-]+/){agent}([-\w]*)?(/|\.js|\.mjs|\.py|$)", a):
                    return agent
    return None


@dataclass
class Rules:
    idle_s: float
    tail: int
    approval: list[re.Pattern]
    prompt: list[re.Pattern]
    approve_keys: list[str]
    deny_keys: list[str]
    skip: bool = False


def load_rules(path: Path | None = None) -> dict[str, Rules]:
    import yaml

    data = yaml.safe_load((path or Path(__file__).with_name("agents.yaml")).read_text(encoding="utf-8"))
    d = data.get("defaults", {})
    out = {}
    for agent in AGENTS:
        a = {**d, **((data.get("agents") or {}).get(agent) or {})}
        out[agent] = Rules(
            idle_s=float(data.get("idle_s", 4)), tail=int(data.get("tail", 15)),
            approval=[re.compile(p, re.I | re.M) for p in a.get("approval") or []],
            prompt=[re.compile(p, re.I | re.M) for p in a.get("prompt") or []],
            approve_keys=list(a.get("approve_keys") or []), deny_keys=list(a.get("deny_keys") or []),
            skip=bool(a.get("skip", False)),
        )
    return out


def last_lines(screen: str, n: int) -> list[str]:
    lines = [ln.rstrip() for ln in screen.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return lines[-n:]


@dataclass
class Watch:
    """What the pos remembers about one agent pane between polls."""
    agent: str
    agent_pid: int
    screen_hash: str = ""
    changed_at: float = 0.0
    status: str | None = None
    request_id: str | None = None


def assess(w: Watch, screen: str, rules: Rules, now: float) -> tuple[str, str | None, str | None, str | None]:
    """(status, request id, prompt text, summary) for this screen. Updates ``w`` in place."""
    lines = last_lines(screen, rules.tail)
    h = hashlib.sha1("\n".join(lines).encode()).hexdigest()[:12]
    if h != w.screen_hash:
        w.screen_hash, w.changed_at = h, now
    summary = next((ln.strip() for ln in reversed(lines) if ln.strip() and not any(p.search(ln) for p in rules.prompt)), None)
    # A question counts only near the bottom: an answered "(y/n)" higher up is history.
    recent = [ln for ln in lines if ln.strip()][-APPROVAL_LINES:]
    recent_text = "\n".join(recent)
    if any(p.search(recent_text) for p in rules.approval):
        return "waiting_approval", f"tmux-{h}", recent_text.strip()[-300:], summary
    idle = now - w.changed_at
    at_prompt = bool(recent) and any(p.search(recent[-1]) for p in rules.prompt)
    if idle >= rules.idle_s and (at_prompt or idle >= QUIET_S):
        return "waiting_input", f"tmux-{h}", None, summary
    return "running", None, None, summary
