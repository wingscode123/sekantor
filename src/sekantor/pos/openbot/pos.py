"""The OpenBot pos (FR-06): OpenBot agents through OpenBot's own Local scripts API.

API (nightly-labs/openbot docs/automation.md): loopback HTTP, URL and bearer token in
``<userData>/automation/{url,token}`` while at least one agent has Local scripts on; new port and
token on every OpenBot start. SeKantor only reads (ADR-0021), and never answers or sends messages to an agent:

- ``GET /v1/agents`` and ``GET /v1/agents/{id}/pending`` (reads are not rate limited)
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from sekantor.pos.claude_code.translate import new_event_id
from sekantor.pos.hub import connect, poll

log = logging.getLogger("sekantor.pos.openbot")
HOST = {"app": "openbot", "confidence": 1.0, "via": ["openbot_api"]}


def user_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "OpenBot"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenBot"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "OpenBot"


def automation_dir() -> Path:
    override = os.environ.get("OPENBOT_AUTOMATION_DIR")
    return Path(override) if override else user_data_dir() / "automation"


def installed() -> bool:
    return user_data_dir().is_dir()


class OpenBotApi:
    """Reads url and token on every (re)connect; never logs the token."""

    def __init__(self, folder: Path | None = None, transport: httpx.BaseTransport | None = None):
        self.folder = folder or automation_dir()
        self.transport = transport
        self.client: httpx.Client | None = None
        self.url: str | None = None

    def connect(self) -> bool:
        try:
            url = (self.folder / "url").read_text(encoding="utf-8").strip()
            token = (self.folder / "token").read_text(encoding="utf-8").strip()
        except OSError:
            self.close()
            return False
        if self.client is None or url != self.url:
            self.close()
            self.url = url
            self.client = httpx.Client(base_url=url, timeout=10, transport=self.transport,
                                       headers={"Authorization": f"Bearer {token}"})
        else:
            self.client.headers["Authorization"] = f"Bearer {token}"
        return True

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        self.client, self.url = None, None

    def get(self, path: str):
        if self.client is None and not self.connect():
            return None
        r = self.client.get(path)
        if r.status_code == 401:  # OpenBot restarted: new token
            if not self.connect():
                return None
            r = self.client.get(path)
        r.raise_for_status()
        return r.json()

def describe(pending: dict) -> dict:
    """Status and request for one agent from its pending list."""
    for a in pending.get("approvals") or []:
        cmd = a.get("command") or a.get("reason") or a.get("kind")
        return {"status": "waiting_approval", "summary": f"Wants to run: {cmd}" if a.get("command") else a.get("reason"),
                "request": {"kind": "tool", "tool": a.get("kind") or "command", "input": cmd, "id": a["requestId"]},
                "cwd": a.get("cwd")}
    for p in pending.get("prompts") or []:
        questions = p.get("questions") or []
        if p.get("requiresOpenBot") or len(questions) != 1:
            return {"status": "waiting_input", "summary": "A question that has to be answered in OpenBot.",
                    "request": {"kind": "question", "id": p["requestId"]}}
        q = questions[0]
        options = ", ".join(o.get("label", "") for o in q.get("options") or [])
        summary = (q.get("question") or q.get("header") or "A question") + (f" ({options})" if options else "")
        return {"status": "waiting_input", "summary": summary, "request": {"kind": "input", "id": p["requestId"]}}
    for b in pending.get("browserTakeovers") or []:
        return {"status": "waiting_input", "summary": "Wants you to take over the browser in OpenBot.",
                "request": {"kind": "question", "id": b["requestId"]}}
    return {"status": "done", "summary": "Idle", "request": None}


class OpenBotPos:
    def __init__(self, api: OpenBotApi, hub, agents_root: Path | None = None):
        self.api = api
        self.hub = hub
        self.agents_root = agents_root or Path.home() / "OpenBot" / "Agents"
        self.known: dict[str, dict] = {}  # session id -> last description (+ agent)
        self.reachable: bool | None = None  # log only when this changes, not on every poll

    def _event(self, agent: dict, d: dict | None, **kw) -> dict:
        cwd = (d or {}).get("cwd") or str(self.agents_root / agent["id"])
        ev = {"v": 1, "event_id": new_event_id(), "ts": datetime.now(timezone.utc).isoformat(), "source": "openbot",
              "session_id": f"openbot:{agent['id']}", "agent": {"name": agent.get("name") or "openbot"},
              "host": HOST, "workspace": {"cwd": cwd}, "type": "status_changed", **kw}
        return {k: v for k, v in ev.items() if v is not None}

    def tick(self) -> None:
        try:
            agents = self.api.get("/v1/agents")
        except (httpx.HTTPError, ValueError) as e:
            if self.reachable is not False:
                log.info("OpenBot not reachable (%s); polling on quietly", type(e).__name__)
            self.reachable = False
            agents = None
        else:
            if self.reachable is False:
                log.info("OpenBot reachable again")
            self.reachable = True
        seen = set()
        for agent in agents or []:
            sid = f"openbot:{agent['id']}"
            seen.add(sid)
            try:
                pending = self.api.get(f"/v1/agents/{quote(agent['id'], safe='')}/pending") or {}
            except (httpx.HTTPError, ValueError):
                continue
            d = describe(pending)
            prev = self.known.get(sid)
            if prev is None:
                self.hub.post_event(self._event(agent, d, type="session_started", status=d["status"], summary=d["summary"],
                                                request=d["request"]))
            elif (prev["status"], (prev["request"] or {}).get("id")) != (d["status"], (d["request"] or {}).get("id")):
                self.hub.post_event(self._event(agent, d, status=d["status"], summary=d["summary"],
                                                request=d["request"]))
            self.known[sid] = {**d, "agent": agent}
        if agents is not None or not self.api.connect():
            for sid in [s for s in self.known if s not in seen]:
                gone = self.known.pop(sid)
                self.hub.post_event(self._event(gone["agent"], None, type="session_ended", status="ended",
                                                summary="Local scripts off, or OpenBot quit"))


def main(interval: float = 3.0) -> None:
    pos = OpenBotPos(OpenBotApi(), connect("openbot"))
    log.info("watching OpenBot agents with Local scripts on (%s)", automation_dir())
    poll(pos.tick, interval, log)
