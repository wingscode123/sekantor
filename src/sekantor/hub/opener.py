"""FR-14 "Open in source": bring the app where a session runs to the front.

Local only, no network, no shell: every command is an argument list or a URL handed to the OS, so a
path from an event cannot inject a command (Windows .cmd shims are avoided on purpose).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from sekantor import labels
from sekantor.hub.status import SessionState


@dataclass
class Plan:
    label: str                 # "Open in VS Code"
    kind: str                  # "url" | "exec" | "folder"
    target: list[str] | str    # argv, URL or folder


def _open_url_or_path(target: str) -> None:
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _orca_cli() -> str | None:
    from sekantor.pos.orca.pos import orca_cli

    return orca_cli()


def _app(name: str) -> list[str] | None:
    """A command that starts (or focuses: these are single-instance apps) a desktop app."""
    if sys.platform == "darwin":
        return ["open", "-a", {"openbot": "OpenBot", "claude-desktop": "Claude"}[name]]
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if name == "openbot":
            exe = local / "Programs" / "OpenBot" / "OpenBot.exe"
            return [str(exe)] if exe.exists() else None
        update = local / "AnthropicClaude" / "Update.exe"  # Squirrel launcher of Claude desktop
        return [str(update), "--processStart", "claude.exe"] if update.exists() else None
    return None


def plan(s: SessionState, which: Callable[[str], str | None] = shutil.which) -> Plan | None:
    """How this session would be opened, or None when there is no way."""
    app = s.host.app if s.host else None
    cwd = s.workspace.cwd
    folder = cwd if cwd and Path(cwd).is_dir() else None
    if app in ("vscode", "cursor") and folder:
        scheme = "vscode" if app == "vscode" else "cursor"
        return Plan(f"Open in {labels.host(app)}", "url", f"{scheme}://file/{quote(Path(folder).as_posix(), safe='/:')}")
    if app == "orca":
        cli = _orca_cli()
        if cli:
            parts = s.session_id.split(":")
            if parts[0] == "orca" and len(parts) >= 3:  # a terminal the Orca pos watches
                return Plan("Open in Orca", "exec", [cli, "terminal", "switch", "--terminal", parts[1], "--json"])
            if folder:
                return Plan("Open in Orca", "exec", [cli, "worktree", "activate", "--worktree", f"path:{folder}", "--json"])
    if app == "tmux" and s.session_id.startswith("tmux:") and which("tmux"):
        pane = s.session_id.split(":")[1]
        return Plan("Open in tmux", "exec", ["tmux", "switch-client", "-t", pane, ";", "select-pane", "-t", pane])
    if app in ("openbot", "claude-desktop"):
        cmd = _app(app)
        if cmd:
            return Plan(f"Open {labels.host(app)}", "exec", cmd)
    if folder:
        return Plan("Open folder", "folder", folder)
    return None


def run(p: Plan) -> None:
    if p.kind == "exec":
        subprocess.Popen(p.target, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
    else:
        _open_url_or_path(p.target)
