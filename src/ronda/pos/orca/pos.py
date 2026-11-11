"""The Orca pos (FR-05): CLI agents other than Claude Code in Orca terminals, through the `orca` CLI.

Claude Code inside Orca (chat or terminal) already reports through its hooks, so this pos only covers
the other agents Orca can launch in a terminal (codex, opencode, gemini, aider). It reuses the tmux
pos's screen logic over a different transport:

- one ``orca terminal list --json`` per cycle (the CLI is slow on a busy machine): ``agentIdentity``
  names the agent, ``preview`` is the screen tail, ``incarnationId`` identifies the run;
- answers with ``orca terminal send`` (text and Enter sent separately, as Orca asks for agent menus).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import zlib
from pathlib import Path

from ronda.pos.tmux.detect import AGENTS, Pane
from ronda.pos.tmux.pos import TmuxPos

log = logging.getLogger("ronda.pos.orca")
HOST = {"app": "orca", "confidence": 1.0, "via": ["orca_cli"]}


def orca_cli() -> str | None:
    env = os.environ.get("ORCA_CLI_COMMAND")
    if env and Path(env).exists():
        return env
    found = shutil.which("orca")
    if found:
        return found
    win = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "orca" / "resources" / "bin" / "orca.exe"
    return str(win) if win.exists() else None


class OrcaTerminals:
    """Tmux-shaped transport over the Orca CLI."""

    def __init__(self, cli: str, runner=subprocess.run, timeout: float = 60):
        self.cli = cli
        self.runner = runner
        self.timeout = timeout
        self.preview: dict[str, str] = {}

    def _run(self, *args: str) -> str | None:
        try:
            p = self.runner([self.cli, *args, "--json"], capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return p.stdout if p.returncode == 0 else None

    def panes(self) -> list[Pane]:
        out = self._run("terminal", "list")
        if not out:
            return []
        try:
            data = json.loads(out)
        except ValueError:
            return []
        terms = (data.get("result") or data).get("terminals") or []
        panes = []
        self.preview = {}
        for t in terms:
            agent = (t.get("agentIdentity") or "").lower()
            if agent not in AGENTS or not t.get("connected") or not t.get("writable") or t.get("orphaned"):
                continue
            ident = zlib.crc32((t.get("incarnationId") or t["handle"]).encode()) or 1
            self.preview[t["handle"]] = t.get("preview") or ""
            cwd = t.get("worktreePath") or ""
            panes.append(Pane(t["handle"], Path(cwd).name or "orca", (t.get("tabId") or "")[:8], ident, agent, cwd))
        return panes

    def capture(self, handle: str) -> str | None:
        return self.preview.get(handle)

    def send_keys(self, handle: str, keys: list[str]) -> bool:
        for k in keys:
            args = ["--enter"] if k == "Enter" else ["--text", "\x1b" if k == "Escape" else k]
            if self._run("terminal", "send", "--terminal", handle, *args) is None:
                return False
        return True

    def send_text(self, handle: str, text: str) -> bool:
        return (self._run("terminal", "send", "--terminal", handle, "--text", text) is not None
                and self._run("terminal", "send", "--terminal", handle, "--enter") is not None)


def make_pos(hub, transport: OrcaTerminals) -> TmuxPos:
    def find(pane: Pane):
        return (pane.command, pane.pid) if pane.command in AGENTS else None

    return TmuxPos(transport, hub, find=find, host=HOST, prefix="orca", real_pid=False)


def main(interval: float = 10.0) -> None:
    from ronda import config
    from ronda.hub.auth import read_token
    from ronda.pos.tmux.pos import HubApi

    logging.basicConfig(level=logging.INFO, format="%(asctime)s orca %(message)s", datefmt="%H:%M:%S")
    cli = orca_cli()
    if not cli:
        raise SystemExit("The orca CLI was not found.")
    token = read_token(config.token_path())
    if not token:
        raise SystemExit("No hub token: run `ronda up` first.")
    pos = make_pos(HubApi(config.hub_url(), token), OrcaTerminals(cli))
    log.info("watching non-Claude agents in Orca terminals every %.0fs", interval)
    try:
        pos.run(interval)
    except KeyboardInterrupt:
        pass
