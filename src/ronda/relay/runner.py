"""``ronda relay``: follows the hub's stream and fans changes out to Telegram and webhooks (ADR-0011)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ronda import config
from ronda.relay.common import HubClient, log
from ronda.relay.telegram import TelegramApi, TelegramChannel, TelegramError, load_config
from ronda.relay.webhook import WebhookChannel, parse


class Relay:
    def __init__(self, channels: list):
        self.channels = channels
        self.state: dict[str, dict] = {}

    async def handle(self, msg: dict) -> None:
        if msg.get("type") == "snapshot":
            # What happened while the relay was away is not news.
            self.state = {s["session_id"]: s for s in msg.get("sessions", [])}
        elif msg.get("type") == "session":
            s = msg["session"]
            prev = self.state.get(s["session_id"])
            self.state[s["session_id"]] = s
            for ch in self.channels:
                try:
                    await ch.on_change(prev, s)
                except Exception as e:
                    log.warning("%s: %s", ch.name, type(e).__name__)


def load_webhooks(home: Path):
    import tomllib

    try:
        with open(config.config_path(home), "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return [], []
    return parse(data.get("webhooks"))


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
    relay = Relay(channels)

    async def follow():
        async for msg in hub.stream():
            await relay.handle(msg)

    await asyncio.gather(follow(), *pollers)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s relay %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
