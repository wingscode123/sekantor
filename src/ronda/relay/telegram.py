"""Telegram channel (FR-31, ADR-0012): notifications with Approve/Deny buttons, replies by
replying to a message. Long polling only; answers only paired chats."""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ronda.config import risky_match
from ronda.labels import TITLES
from ronda.relay.common import HubClient, log, pending_request_id, redact, should_notify, who

API = "https://api.telegram.org"
CMD_LIMIT = 300
TEXT_LIMIT = 600


class TelegramError(Exception):
    pass


class TelegramApi:
    """Bot API over httpx. The token is part of the URL, so URLs are never logged."""

    def __init__(self, token: str, client: httpx.AsyncClient | None = None, base: str = API):
        self._url = f"{base}/bot{token}/"
        self.client = client or httpx.AsyncClient(timeout=40)

    async def call(self, method: str, **params: Any) -> Any:
        try:
            r = await self.client.post(self._url + method, json={k: v for k, v in params.items() if v is not None},
                                       timeout=(params.get("timeout") or 0) + 15)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(f"{method}: {type(e).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', 'failed')}")
        return data["result"]


# --- ~/.ronda/telegram.json ----------------------------------------------------------

def config_path(home: Path) -> Path:
    return home / "telegram.json"


def load_config(home: Path) -> dict | None:
    try:
        data = json.loads(config_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not data.get("token") or not data.get("chats"):
        return None
    return data


def save_config(home: Path, token: str, chats: list[int], bot: str) -> Path:
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"token": token, "chats": chats, "bot": bot, "paired_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    return path


async def pair(api: TelegramApi, code: str, deadline_s: float = 300, clock=time.monotonic) -> tuple[int, str]:
    """Wait for '/pair <code>' and return (chat id, chat name). Raises TimeoutError."""
    offset = None
    end = clock() + deadline_s
    # Skip anything sent before pairing started.
    old = await api.call("getUpdates", timeout=0)
    if old:
        offset = old[-1]["update_id"] + 1
    while clock() < end:
        updates = await api.call("getUpdates", offset=offset, timeout=min(25, max(1, int(end - clock()))),
                                 allowed_updates=["message"])
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            text = (msg.get("text") or "").strip()
            command, _, arg = text.partition(" ")
            if (command == "/pair" or command.startswith("/pair@")) and arg.strip() == code:
                chat = msg["chat"]
                await api.call("getUpdates", offset=offset, timeout=0)  # acknowledge
                await api.call("sendMessage", chat_id=chat["id"], text="Paired. Ronda will tell you here when an agent needs you.")
                return chat["id"], chat.get("username") or chat.get("title") or chat.get("first_name") or str(chat["id"])
    raise TimeoutError("no /pair message arrived in time")


# --- the channel ----------------------------------------------------------------------

@dataclass
class Open:
    """A Telegram message that still offers an answer to one pending request."""
    session_id: str
    request_id: str
    kind: str  # "approval" | "reply"
    chat_id: int
    message_id: int
    text: str


class TelegramChannel:
    name = "telegram"

    def __init__(self, api: TelegramApi, chats: list[int], hub: HubClient, risky: list[str]):
        self.api = api
        self.chats = set(int(c) for c in chats)
        self.hub = hub
        self.risky = risky
        self.open: dict[str, Open] = {}           # callback key -> message
        self.replies: dict[tuple[int, int], str] = {}  # (chat, message id) -> key
        self.offset: int | None = None

    # -- hub side --------------------------------------------------------------------

    async def on_change(self, prev: dict | None, s: dict, announce: bool = True) -> None:
        current = pending_request_id(s)
        for key, o in list(self.open.items()):
            if o.session_id == s["session_id"] and o.request_id != current:
                await self._close(key, "Answered elsewhere." if s["status"] != "ended" else "Session ended.")
        if announce and should_notify(prev, s):
            await self._announce(s)

    def _text(self, s: dict) -> tuple[str, str | None, bool]:
        """(message, kind of answer offered, risky)"""
        status = s["status"]
        lines = [TITLES.get(status, status), who(s)]
        caps = set(s.get("capabilities") or [])
        req = s.get("request") or {}
        kind, risky = None, False
        if status == "waiting_approval":
            if req.get("input"):
                lines.append(f"Wants to run: {redact(req['input'], CMD_LIMIT)}")
            risky = bool(risky_match(req.get("input"), self.risky))
            if caps & {"approve", "deny"} and req.get("id"):
                kind = "approval"
                if risky:
                    lines.append("Risky command: approve it on your computer. You can deny it here.")
        elif s.get("summary"):
            lines.append(redact(s["summary"], TEXT_LIMIT))
        if status == "waiting_input" and "reply" in caps and req.get("id"):
            kind = "reply"
            lines.append("Reply to this message to answer.")
        return "\n".join(lines), kind, risky

    async def _announce(self, s: dict) -> None:
        text, kind, risky = self._text(s)
        req_id = (s.get("request") or {}).get("id")
        caps = set(s.get("capabilities") or [])
        for chat in self.chats:
            key = secrets.token_urlsafe(9)
            markup = None
            if kind == "approval":
                row = []
                if "approve" in caps and not risky:
                    row.append({"text": "Approve", "callback_data": f"a:{key}"})
                if "deny" in caps:
                    row.append({"text": "Deny", "callback_data": f"d:{key}"})
                markup = {"inline_keyboard": [row]} if row else None
            try:
                msg = await self.api.call("sendMessage", chat_id=chat, text=text, reply_markup=markup)
            except Exception as e:
                log.warning("telegram send failed: %s", e)
                continue
            if kind:
                self.open[key] = Open(s["session_id"], req_id, kind, chat, msg["message_id"], text)
                if kind == "reply":
                    self.replies[(chat, msg["message_id"])] = key

    async def _close(self, key: str, note: str) -> None:
        o = self.open.pop(key, None)
        if o is None:
            return
        self.replies.pop((o.chat_id, o.message_id), None)
        try:
            await self.api.call("editMessageText", chat_id=o.chat_id, message_id=o.message_id,
                                text=f"{o.text}\n\n{note}", reply_markup={"inline_keyboard": []})
        except Exception:
            pass  # too old to edit, deleted, or unchanged

    # -- Telegram side ---------------------------------------------------------------

    async def poll_once(self, timeout: int = 25) -> None:
        updates = await self.api.call("getUpdates", offset=self.offset, timeout=timeout,
                                      allowed_updates=["message", "callback_query"])
        for u in updates:
            self.offset = u["update_id"] + 1
            try:
                await self.handle_update(u)
            except Exception as e:
                log.warning("telegram update failed: %s", type(e).__name__)

    async def handle_update(self, u: dict) -> None:
        if "callback_query" in u:
            return await self._callback(u["callback_query"])
        msg = u.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        if chat not in self.chats:
            log.info("ignored a message from an unpaired chat")
            return
        reply_to = (msg.get("reply_to_message") or {}).get("message_id")
        text = (msg.get("text") or "").strip()
        if reply_to and (chat, reply_to) in self.replies:
            return await self._reply(chat, msg["message_id"], self.replies[(chat, reply_to)], text)
        if text.startswith("/status"):
            return await self._status(chat)
        await self.api.call("sendMessage", chat_id=chat,
                            text="Reply to one of my messages to answer that agent. /status lists who needs you.")

    async def _callback(self, cq: dict) -> None:
        chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
        if chat not in self.chats:
            log.info("ignored a button press from an unpaired chat")
            return
        verb, _, key = (cq.get("data") or "").partition(":")
        o = self.open.get(key)
        if o is None or o.kind != "approval" or verb not in ("a", "d"):
            await self.api.call("answerCallbackQuery", callback_query_id=cq["id"], text="This request is no longer open.")
            return
        action = "approve" if verb == "a" else "deny"
        code, data = await self.hub.post_action(o.session_id, {"type": action, "request_id": o.request_id}, "telegram")
        if code == 202:
            await self.api.call("answerCallbackQuery", callback_query_id=cq["id"],
                                text="Approved." if action == "approve" else "Denied.")
            await self._close(key, f"{'Approved' if action == 'approve' else 'Denied'} from Telegram.")
        else:
            await self.api.call("answerCallbackQuery", callback_query_id=cq["id"],
                                text=data.get("message") or "Not sent.", show_alert=True)
            if data.get("error") in ("not_waiting", "stale_request"):
                await self._close(key, "Answered elsewhere.")

    async def _reply(self, chat: int, message_id: int, key: str, text: str) -> None:
        o = self.open.get(key)
        if o is None or not text:
            await self.api.call("sendMessage", chat_id=chat, reply_to_message_id=message_id,
                                text="That session is no longer waiting." if o is None else "Write a reply first.")
            return
        code, data = await self.hub.post_action(o.session_id, {"type": "reply", "request_id": o.request_id, "text": text},
                                                "telegram")
        if code == 202:
            await self._close(key, "Replied from Telegram.")
            await self.api.call("sendMessage", chat_id=chat, reply_to_message_id=message_id, text="Sent.")
        else:
            await self.api.call("sendMessage", chat_id=chat, reply_to_message_id=message_id,
                                text=data.get("message") or "Not sent.")

    async def _status(self, chat: int) -> None:
        try:
            sessions = await self.hub.sessions()
        except Exception:
            await self.api.call("sendMessage", chat_id=chat, text="The hub is not answering.")
            return
        needs = [s for s in sessions if s.get("needs_you")]
        if not needs:
            text = "Nobody needs you."
        else:
            text = "\n".join(f"{TITLES.get(s['status'], s['status'])}: {who(s)}" for s in needs[:10])
        await self.api.call("sendMessage", chat_id=chat, text=text)
