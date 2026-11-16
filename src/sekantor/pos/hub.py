"""What the polling pos processes (tmux, Orca, OpenBot) share: start-up, a hub client and the poll loop."""

from __future__ import annotations

import logging
import time
from typing import Callable


class HubApi:
    """Minimal synchronous hub client (the pos loop is synchronous)."""

    def __init__(self, base_url: str, token: str):
        import httpx

        self.base = base_url.rstrip("/")
        self.client = httpx.Client(timeout=5, headers={"Authorization": f"Bearer {token}"})

    def post_event(self, event: dict) -> bool:
        return self.client.post(f"{self.base}/v1/events", json=event).status_code == 202


def connect(name: str) -> HubApi:
    """Start a pos process: end with the hub, log as ``name``, and connect with the hub token."""
    from sekantor import config
    from sekantor.hub.auth import read_token
    from sekantor.lifeline import start_parent_watch

    start_parent_watch()  # end with the hub, even when it is force-stopped
    from sekantor import logs

    logs.setup(name)
    token = read_token(config.token_path())
    if not token:
        raise SystemExit("No hub token: run `sekantor up` first.")
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
