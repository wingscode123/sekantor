"""What the polling pos processes (tmux, Orca, OpenBot) share: start-up, a hub client and the poll loop."""

from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import quote


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


def connect(name: str) -> HubApi:
    """Start a pos process: end with the hub, log as ``name``, and connect with the hub token."""
    from ronda import config
    from ronda.hub.auth import read_token
    from ronda.lifeline import start_parent_watch

    start_parent_watch()  # end with the hub, even when it is force-stopped
    from ronda import logs

    logs.setup(name)
    token = read_token(config.token_path())
    if not token:
        raise SystemExit("No hub token: run `ronda up` first.")
    return HubApi(config.hub_url(), token)


def poll(tick: Callable[[], None], interval: float, log: logging.Logger) -> None:
    """Call ``tick`` every ``interval`` seconds until Ctrl+C. A failed tick is logged and the loop goes on."""
    try:
        while True:
            try:
                tick()
            except Exception as e:
                log.warning("tick failed: %s", type(e).__name__)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
