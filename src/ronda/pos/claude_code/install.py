"""Install / uninstall ronda-hook in Claude Code settings (ADR-0004).

Appends Ronda's own handlers and never touches anyone else's (Orca installs hooks too). Backs up
the file before every change. Our handlers are recognised by the command ending in ``ronda-hook``.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ADR-0002 / ADR-0021. Every handler runs async: Ronda only watches, so no hook can hold an agent up.
EVENTS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse",
    "PostToolUseFailure", "PermissionDenied", "Notification", "Stop", "StopFailure", "SessionEnd",
]
HOOK_NAMES = {"ronda-hook", "ronda-hook.exe"}


def settings_path(scope: str) -> Path:
    if scope == "project":
        return Path.cwd() / ".claude" / "settings.local.json"
    if scope == "global":
        base = os.environ.get("CLAUDE_CONFIG_DIR")
        return (Path(base) if base else Path.home() / ".claude") / "settings.json"
    raise ValueError(f"unknown scope {scope!r}")


def hook_executable() -> Path | None:
    """The ronda-hook next to the running Python first (same venv), then PATH."""
    name = "ronda-hook.exe" if sys.platform == "win32" else "ronda-hook"
    sibling = Path(sys.executable).parent / name
    if sibling.is_file():
        return sibling.resolve()
    found = shutil.which("ronda-hook")
    return Path(found).resolve() if found else None


def is_ours(handler: dict) -> bool:
    cmd = str(handler.get("command", ""))
    return Path(cmd.replace("\\", "/")).name.lower() in HOOK_NAMES


def handler_for(event: str, exe: Path) -> dict:
    # Exec form (`args`): shell form runs in Git Bash on Windows, where a backslash path breaks
    # (docs/spike/claude-hooks.md). SessionEnd stays synchronous: an async hook may be killed when the
    # process exits, and a SessionEnd was the one event lost under load in dogfooding (ADR-0017). It only
    # POSTs with a short timeout and never waits for an answer.
    h = {"type": "command", "command": exe.as_posix(), "args": []}
    if event == "SessionEnd":
        return {**h, "timeout": 5}
    return {**h, "async": True, "timeout": 10}


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)  # invalid JSON raises: never overwrite a file we cannot read
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    dst = path.with_name(f"{path.name}.ronda-backup-{datetime.now():%Y%m%d%H%M%S}")
    n = 1
    while dst.exists():
        dst = path.with_name(f"{path.name}.ronda-backup-{datetime.now():%Y%m%d%H%M%S}-{n}")
        n += 1
    shutil.copy2(path, dst)
    return dst


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".ronda-tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _strip_ours(hooks: dict) -> int:
    removed = 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for g in groups:
            hs = g.get("hooks", []) if isinstance(g, dict) else []
            kept = [h for h in hs if not (isinstance(h, dict) and is_ours(h))]
            removed += len(hs) - len(kept)
            if kept:
                kept_groups.append({**g, "hooks": kept})
            elif not hs:
                kept_groups.append(g)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    return removed


@dataclass
class Result:
    path: Path
    backup: Path | None
    changed: int


def install(path: Path, exe: Path) -> Result:
    data = _read(path)
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    _strip_ours(hooks)
    for event in EVENTS:
        hooks.setdefault(event, []).append({"hooks": [handler_for(event, exe)]})
    data["hooks"] = hooks
    backup = _backup(path)
    _write(path, data)
    return Result(path, backup, len(EVENTS))


def uninstall(path: Path) -> Result:
    data = _read(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return Result(path, None, 0)
    removed = _strip_ours(hooks)
    if not removed:
        return Result(path, None, 0)
    if hooks:
        data["hooks"] = hooks
    else:
        del data["hooks"]
    backup = _backup(path)
    _write(path, data)
    return Result(path, backup, removed)


@dataclass
class Installed:
    path: Path
    events: list[str] = field(default_factory=list)
    commands: set[str] = field(default_factory=set)
    handlers: dict[str, dict] = field(default_factory=dict)

    def current_shape(self) -> bool:
        """False for an install from before ADR-0021: a handler with ``--wait``, a synchronous one (except
        SessionEnd), one with asyncRewake, or one in shell form. `ronda doctor` then says to reinstall."""
        def ok(event: str, h: dict) -> bool:
            if h.get("args") != [] or "asyncRewake" in h:
                return False
            if event == "SessionEnd":
                return "async" not in h and (h.get("timeout") or 0) >= 5
            return h.get("async") is True

        return all(ok(e, h) for e, h in self.handlers.items())

    @property
    def complete(self) -> bool:
        return set(EVENTS) <= set(self.events)

    @property
    def commands_exist(self) -> bool:
        return bool(self.commands) and all(Path(c).is_file() for c in self.commands)


def inspect(path: Path) -> Installed:
    out = Installed(path)
    try:
        data = _read(path)
    except (ValueError, OSError):
        return out
    for event, groups in (data.get("hooks") or {}).items():
        for g in groups if isinstance(groups, list) else []:
            for h in g.get("hooks", []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and is_ours(h):
                    out.events.append(event)
                    out.commands.add(h["command"])
                    out.handlers[event] = h
    return out
