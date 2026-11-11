"""Generic webhooks (FR-32): POST on the same moments as notifications, redacted, optionally signed.

config.toml:

    [[webhooks]]
    url = "https://ntfy.sh/my-topic"
    format = "ntfy"                     # json (default), ntfy, text, slack
    statuses = ["waiting_approval", "waiting_input", "error"]   # the default
    secret = "..."                      # optional: X-Ronda-Signature: sha256=<hmac of the body>
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from ronda.relay.common import TITLES, log, redact, should_notify, who

DEFAULT_STATUSES = ("waiting_approval", "waiting_input", "error")
FORMATS = ("json", "text", "ntfy", "slack")
RETRIES = (0, 2, 8)  # seconds before each attempt


@dataclass
class Webhook:
    url: str
    format: str = "json"
    statuses: tuple[str, ...] = DEFAULT_STATUSES
    secret: str | None = None


@dataclass
class WebhookConfigError:
    index: int
    message: str


def parse(entries: list[dict] | None) -> tuple[list[Webhook], list[WebhookConfigError]]:
    hooks, errors = [], []
    for i, e in enumerate(entries or []):
        if not isinstance(e, dict):
            errors.append(WebhookConfigError(i, "not a table"))
            continue
        url = str(e.get("url", ""))
        u = urlparse(url)
        local = u.hostname in ("127.0.0.1", "localhost", "::1")
        if u.scheme != "https" and not (u.scheme == "http" and local):
            errors.append(WebhookConfigError(i, "url must be https (http only for localhost)"))
            continue
        fmt = e.get("format", "json")
        if fmt not in FORMATS:
            errors.append(WebhookConfigError(i, f"format must be one of {', '.join(FORMATS)}"))
            continue
        statuses = tuple(e.get("statuses") or DEFAULT_STATUSES)
        hooks.append(Webhook(url=url, format=fmt, statuses=statuses, secret=e.get("secret")))
    return hooks, errors


def body_for(hook: Webhook, s: dict) -> tuple[bytes, str]:
    title = TITLES.get(s["status"], s["status"])
    line = who(s)
    req = s.get("request") or {}
    detail = redact(req.get("input"), 300) if s["status"] == "waiting_approval" and req.get("input") \
        else redact(s.get("summary"), 500)
    if hook.format == "text":
        return "\n".join(x for x in (f"{title}: {line}", detail) if x).encode(), "text/plain; charset=utf-8"
    if hook.format == "ntfy":
        return "\n".join(x for x in (line, detail) if x).encode(), "text/plain; charset=utf-8"
    if hook.format == "slack":
        return json.dumps({"text": "\n".join(x for x in (f"*{title}*: {line}", detail) if x)}).encode(), "application/json"
    payload = {
        "v": 1, "type": "session.status", "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": s["session_id"], "source": s.get("source"), "status": s["status"], "title": title,
        "host": (s.get("host") or {}).get("app"), "cwd": (s.get("workspace") or {}).get("cwd"),
        "branch": (s.get("workspace") or {}).get("branch"), "detail": detail, "needs_you": s.get("needs_you"),
    }
    return json.dumps(payload).encode(), "application/json"


NTFY_TAGS = {"waiting_approval": "warning", "waiting_input": "speech_balloon", "error": "rotating_light"}


def ntfy_headers(hook: Webhook, s: dict) -> dict[str, str]:
    """ntfy reads the title, priority and tags from headers (https://docs.ntfy.sh/publish/)."""
    if hook.format != "ntfy":
        return {}
    status = s["status"]
    return {"Title": TITLES.get(status, status),
            "Priority": "high" if status in ("waiting_approval", "error") else "default",
            "Tags": NTFY_TAGS.get(status, "bell")}


class WebhookChannel:
    name = "webhook"

    def __init__(self, hooks: list[Webhook], client: httpx.AsyncClient | None = None, sleep=asyncio.sleep):
        self.hooks = hooks
        self.client = client or httpx.AsyncClient(timeout=5)
        self.sleep = sleep
        self.tasks: set[asyncio.Task] = set()

    async def on_change(self, prev: dict | None, s: dict, announce: bool = True) -> None:
        if not announce or not should_notify(prev, s):
            return
        for hook in self.hooks:
            if s["status"] in hook.statuses:
                t = asyncio.create_task(self.send(hook, s))
                self.tasks.add(t)
                t.add_done_callback(self.tasks.discard)

    async def send(self, hook: Webhook, s: dict) -> bool:
        body, ctype = body_for(hook, s)
        headers = {"Content-Type": ctype, "User-Agent": "ronda-relay", **ntfy_headers(hook, s)}
        if hook.secret:
            headers["X-Ronda-Signature"] = "sha256=" + hmac.new(hook.secret.encode(), body, hashlib.sha256).hexdigest()
        host = urlparse(hook.url).hostname
        for delay in RETRIES:
            if delay:
                await self.sleep(delay)
            try:
                r = await self.client.post(hook.url, content=body, headers=headers)
                if r.status_code < 500 and r.status_code != 429:
                    if r.status_code >= 400:
                        log.warning("webhook %s answered %s", host, r.status_code)
                    return r.status_code < 400
            except httpx.HTTPError as e:
                log.warning("webhook %s: %s", host, type(e).__name__)
        return False
