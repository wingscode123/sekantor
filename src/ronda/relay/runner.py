"""``ronda relay``: follows the hub's stream and fans changes out to Telegram and webhooks (ADR-0011)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ronda import config
from ronda.relay.common import HubClient, log
from ronda.relay.telegram import TelegramApi, TelegramChannel, TelegramError, load_config
from ronda.relay.webhook import WebhookChannel, parse


def snoozed(s: dict) -> bool:
    from datetime import datetime, timezone

    until = s.get("snoozed_until")
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > datetime.now(timezone.utc)
    except ValueError:
        return False


class Relay:
    def __init__(self, channels: list, quiet=lambda: False):
        self.channels = channels
        self.quiet = quiet
        self.state: dict[str, dict] = {}

    async def handle(self, msg: dict) -> None:
        if msg.get("type") == "snapshot":
            # What happened while the relay was away is not news.
            self.state = {s["session_id"]: s for s in msg.get("sessions", [])}
        elif msg.get("type") == "session":
            s = msg["session"]
            prev = self.state.get(s["session_id"])
            self.state[s["session_id"]] = s
            announce = not snoozed(s) and not self.quiet()  # FR-15, FR-33
            for ch in self.channels:
                try:
                    await ch.on_change(prev, s, announce)
                except Exception as e:
                    log.warning("%s: %s", ch.name, type(e).__name__)


def load_webhooks(home: Path):
    return parse(config.read_toml(home).get("webhooks"))


def configured(home: Path) -> list[str]:
    """Names of the channels that would run, for `ronda up` and `ronda doctor`."""
    names = []
    if load_config(home):
        names.append("telegram")
    hooks, _ = load_webhooks(home)
    if hooks:
        names.append(f"{len(hooks)} webhook{'s' if len(hooks) != 1 else ''}")
    return names


async def run(home: Path | None = None, hub_url: str | None = None) -> None:
    from ronda.hub.auth import read_token

    home = home or config.home()
    token = read_token(home / "token")
    if not token:
        raise SystemExit("No hub token: run `ronda up` first.")
    hub = HubClient(hub_url or config.hub_url(), token)
    settings = config.settings(home)
    channels, pollers = [], []

    tg = load_config(home)
    if tg:
        channel = TelegramChannel(TelegramApi(tg["token"]), tg["chats"], hub, settings.risky)
        channels.append(channel)

        async def poll():
            delay = 1.0
            while True:
                try:
                    await channel.poll_once()
                    delay = 1.0
                except TelegramError as e:
                    log.warning("telegram: %s; retrying in %.0fs", e, delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60.0)
        pollers.append(poll())

    hooks, errors = load_webhooks(home)
    for err in errors:
        log.warning("webhook #%d ignored: %s", err.index + 1, err.message)
    if hooks:
        channels.append(WebhookChannel(hooks))

    if not channels:
        raise SystemExit("Nothing to relay: run `ronda pair telegram` or add [[webhooks]] to config.toml.")
    log.info("relay: %s", ", ".join(ch.name for ch in channels))
    relay = Relay(channels, quiet=settings.quiet)

    async def follow():
        async for msg in hub.stream():
            await relay.handle(msg)

    await asyncio.gather(follow(), *pollers)


def main() -> None:
    from ronda.lifeline import start_parent_watch

    start_parent_watch()  # end with the hub, even when it is force-stopped
    from ronda import logs

    logs.setup("relay")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


SAMPLE = {"session_id": "claude:ronda-test", "source": "claude-code", "status": "waiting_approval", "needs_you": True,
          "host": {"app": "terminal", "confidence": 1.0}, "workspace": {"cwd": "ronda-test", "branch": None},
          "capabilities": [], "request": {"kind": "tool", "tool": "Bash", "input": "echo hello from Ronda"}}


async def send_test(home: Path | None = None) -> list[tuple[str, bool]]:
    """Send one sample 'Approval needed' to every configured channel. Returns (channel, ok) pairs."""
    home = home or config.home()
    results: list[tuple[str, bool]] = []
    hooks, _ = load_webhooks(home)
    if hooks:
        ch = WebhookChannel(hooks)
        for hook in hooks:
            results.append((f"webhook {hook.url.split('/')[2]}", await ch.send(hook, SAMPLE)))
    tg = load_config(home)
    if tg:
        api = TelegramApi(tg["token"])
        for chat in tg["chats"]:
            try:
                await api.call("sendMessage", chat_id=chat, text="Ronda test: the relay can reach you.")
                results.append(("telegram", True))
            except TelegramError:
                results.append(("telegram", False))
    return results
