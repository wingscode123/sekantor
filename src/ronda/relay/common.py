"""Shared pieces of the relay: talking to the hub and describing a session in a few words."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

import httpx

from ronda import labels
from ronda.hub.notify import should_notify as _should_notify
from ronda.relay.redact import redact
from ronda.schema import Status

log = logging.getLogger("ronda.relay")


def should_notify(prev: dict | None, s: dict) -> bool:
    return _should_notify(Status(prev["status"]) if prev else None, Status(s["status"]))


def pending_request_id(s: dict | None) -> str | None:
    if not s or s.get("status") not in ("waiting_approval", "waiting_input"):
        return None
    return (s.get("request") or {}).get("id")


def who(s: dict) -> str:
    """'Claude Code in Orca, shop (feat/checkout)'"""
    text = labels.source(s.get("source") or "Agent")
    host = (s.get("host") or {}).get("app")
    if host:
        text += f" in {labels.host(host)}"
    ws = s.get("workspace") or {}
    if ws.get("cwd"):
        text += f", {Path(ws['cwd'].replace(chr(92), '/')).name}"
        if ws.get("branch"):
            text += f" ({ws['branch']})"
    return text


class HubClient:
    """The relay is an ordinary client of the hub: local token, loopback only."""

    def __init__(self, base_url: str, token: str, client: httpx.AsyncClient | None = None):
        self.base = base_url.rstrip("/")
        self.token = token
        self.client = client or httpx.AsyncClient(timeout=10)

    def _headers(self, channel: str = "api") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Ronda-Channel": channel}

    async def post_action(self, session_id: str, body: dict, channel: str) -> tuple[int, dict]:
        r = await self.client.post(f"{self.base}/v1/sessions/{quote(session_id, safe='')}/actions",
                                   json=body, headers=self._headers(channel))
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}

    async def sessions(self) -> list[dict]:
        r = await self.client.get(f"{self.base}/v1/sessions", headers=self._headers())
        r.raise_for_status()
        return r.json()["sessions"]

    async def stream(self) -> AsyncIterator[dict]:
        """Messages from WS /v1/stream, reconnecting with backoff for as long as the caller iterates."""
        import websockets

        url = "ws" + self.base[4:] + "/v1/stream"
        delay = 1.0
        while True:
            try:
                async with websockets.connect(url, additional_headers=self._headers()) as ws:
                    delay = 1.0
                    async for raw in ws:
                        yield json.loads(raw)
            except (OSError, websockets.WebSocketException) as e:
                log.warning("hub stream: %s; retrying in %.0fs", type(e).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


__all__ = ["HubClient", "pending_request_id", "redact", "should_notify", "who", "log"]
