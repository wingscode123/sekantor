"""The tmux pos (FR-04, FR-23): CLI agents in tmux panes, read from the screen, answered with send-keys.

Runs as its own process (`ronda pos tmux`, started by `ronda up` when tmux exists) and talks to the
hub like any other pos: POST /v1/events, and GET /v1/sessions/{id}/actions/next for answers.
Before sending keys it checks that the pane still runs the same agent process (FR-23).
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

from ronda.pos.claude_code.translate import git_branch, new_event_id
from ronda.pos.tmux.detect import LIST_FORMAT, Pane, Rules, Watch, agent_of, assess, load_rules, parse_panes

log = logging.getLogger("ronda.pos.tmux")
HOST = {"app": "tmux", "confidence": 1.0, "via": ["tmux"]}


class Tmux:
    def __init__(self, binary: str = "tmux", extra: list[str] | None = None, runner=subprocess.run):
        self.cmd = [binary, *(extra or [])]
        self.runner = runner

    def run(self, *args: str) -> str | None:
        try:
            p = self.runner([*self.cmd, *args], capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return p.stdout if p.returncode == 0 else None

    def panes(self) -> list[Pane]:
        out = self.run("list-panes", "-a", "-F", LIST_FORMAT)
        return parse_panes(out) if out else []

    def capture(self, pane_id: str) -> str | None:
        return self.run("capture-pane", "-p", "-J", "-t", pane_id, "-S", "-80")

    def send_keys(self, pane_id: str, keys: list[str]) -> bool:
        return self.run("send-keys", "-t", pane_id, *keys) is not None

    def send_text(self, pane_id: str, text: str) -> bool:
        # -l: literal, so "Enter" in the reply is typed, not pressed
        return (self.run("send-keys", "-t", pane_id, "-l", "--", text) is not None
                and self.run("send-keys", "-t", pane_id, "Enter") is not None)


def find_agent(pane_pid: int) -> tuple[str, int] | None:
    """(agent, pid) of the agent running in this pane, searching the pane's process tree."""
    import psutil

    try:
        root = psutil.Process(pane_pid)
        for p in [root, *root.children(recursive=True)]:
            try:
                agent = agent_of(p.name(), p.cmdline())
            except psutil.Error:
                continue
            if agent:
                return agent, p.pid
    except psutil.Error:
        return None
    return None


class HubApi:
    """Minimal synchronous hub client (the pos loop is synchronous)."""

    def __init__(self, base_url: str, token: str):
        import httpx

        self.base = base_url.rstrip("/")
        self.client = httpx.Client(timeout=5, headers={"Authorization": f"Bearer {token}"})

    def post_event(self, event: dict) -> bool:
        return self.client.post(f"{self.base}/v1/events", json=event).status_code == 202

    def next_action(self, session_id: str, kind: str, request_id: str) -> dict | None:
        r = self.client.get(f"{self.base}/v1/sessions/{quote(session_id, safe='')}/actions/next",
                            params={"for": kind, "request_id": request_id, "wait": 0})
        return r.json().get("action") if r.status_code == 200 else None


class TmuxPos:
    name = "tmux"
    capabilities = {"approve", "deny", "reply"}

    def __init__(self, tmux: Tmux, hub, rules: dict[str, Rules] | None = None,
                 find: Callable[[Pane], tuple[str, int] | None] | None = None, clock: Callable[[], float] = time.monotonic,
                 host: dict = HOST, prefix: str = "tmux", real_pid: bool = True):
        self.tmux = tmux
        self.hub = hub
        self.rules = rules or load_rules()
        self.find = find or (lambda pane: find_agent(pane.pid))
        self.clock = clock
        self.host, self.prefix, self.real_pid = host, prefix, real_pid
        self.watches: dict[str, Watch] = {}  # session id -> watch
        self.panes: dict[str, Pane] = {}     # session id -> pane

    def session_id(self, pane: Pane, agent_pid: int) -> str:
        return f"{self.prefix}:{pane.pane_id}:{agent_pid}"

    def _event(self, sid: str, w: Watch, pane: Pane, **kw) -> dict:
        ev = {"v": 1, "event_id": new_event_id(), "ts": datetime.now(timezone.utc).isoformat(), "source": w.agent,
              "session_id": sid, "agent": {"name": w.agent}, "host": self.host,
              "process": {"pid": w.agent_pid} if self.real_pid else None,
              "workspace": {"cwd": pane.cwd, "branch": git_branch(pane.cwd)}, "type": "status_changed", **kw}
        return {k: v for k, v in ev.items() if v is not None}

    def discover(self) -> dict[str, tuple[Pane, str, int]]:
        found = {}
        for pane in self.tmux.panes():
            hit = self.find(pane)
            if not hit:
                continue
            agent, pid = hit
            if self.rules[agent].skip:
                continue
            found[self.session_id(pane, pid)] = (pane, agent, pid)
        return found

    def tick(self) -> None:
        now = self.clock()
        found = self.discover()
        for sid in list(self.watches):
            if sid not in found:
                w, pane = self.watches.pop(sid), self.panes.pop(sid)
                self.hub.post_event(self._event(sid, w, pane, type="session_ended", status="ended", summary="Agent exited"))
        for sid, (pane, agent, pid) in found.items():
            self.panes[sid] = pane
            w = self.watches.get(sid)
            if w is None:
                w = self.watches[sid] = Watch(agent=agent, agent_pid=pid, changed_at=now)
                self.hub.post_event(self._event(sid, w, pane, type="session_started", status="running",
                                                summary=f"{agent} in {self.host['app']} {pane.session}"))
                w.status = "running"
            screen = self.tmux.capture(pane.pane_id)
            if screen is None:
                continue
            rules = self.rules[agent]
            status, rid, prompt, summary = assess(w, screen, rules, now)
            if status != w.status or rid != w.request_id:
                caps, request = [], None
                if status == "waiting_approval":
                    request = {"kind": "tool", "tool": "terminal", "input": prompt, "id": rid}
                    caps = [c for c, keys in (("approve", rules.approve_keys), ("deny", rules.deny_keys)) if keys]
                elif status == "waiting_input":
                    request, caps = {"kind": "input", "id": rid}, ["reply"]
                if self.hub.post_event(self._event(sid, w, pane, status=status, summary=summary,
                                                   request=request, capabilities=caps)):
                    w.status, w.request_id = status, rid
            if w.request_id and w.status in ("waiting_approval", "waiting_input"):
                kind = "approval" if w.status == "waiting_approval" else "reply"
                try:
                    action = self.hub.next_action(sid, kind, w.request_id)
                except Exception as e:
                    log.warning("actions: %s", type(e).__name__)
                    action = None
                if action:
                    self.act(sid, action)

    def act(self, session_id: str, action: dict) -> bool:
        """Send the answer, but only to the pane that still runs the same agent (FR-23)."""
        w, pane = self.watches.get(session_id), self.panes.get(session_id)
        if not w or not pane:
            return False
        hit = self.find(pane)
        if not hit or hit[1] != w.agent_pid:
            log.warning("not sending to %s: the agent there changed", pane.pane_id)
            return False
        rules = self.rules[w.agent]
        if action["type"] == "approve" and rules.approve_keys:
            ok = self.tmux.send_keys(pane.pane_id, rules.approve_keys)
        elif action["type"] == "deny" and rules.deny_keys:
            ok = self.tmux.send_keys(pane.pane_id, rules.deny_keys)
        elif action["type"] == "reply" and action.get("text"):
            ok = self.tmux.send_text(pane.pane_id, action["text"])
        else:
            return False
        if ok:
            w.request_id = None  # the screen will move on; the next tick reports the new state
        return ok

    def run(self, interval: float = 2.0) -> None:
        while True:
            try:
                self.tick()
            except Exception as e:
                log.warning("tick failed: %s", type(e).__name__)
            time.sleep(interval)


def main(interval: float = 2.0) -> None:
    import shutil

    from ronda import config
    from ronda.hub.auth import read_token

    logging.basicConfig(level=logging.INFO, format="%(asctime)s tmux %(message)s", datefmt="%H:%M:%S")
    if not shutil.which("tmux"):
        raise SystemExit("tmux is not installed.")
    token = read_token(config.token_path())
    if not token:
        raise SystemExit("No hub token: run `ronda up` first.")
    pos = TmuxPos(Tmux(), HubApi(config.hub_url(), token))
    log.info("watching tmux panes every %.0fs", interval)
    try:
        pos.run(interval)
    except KeyboardInterrupt:
        pass
