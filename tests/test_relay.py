"""M3 relay: Telegram channel, pairing, webhooks (no network: fakes and httpx.MockTransport)."""

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from ronda.config import DEFAULT_RISKY
from ronda.relay.runner import Relay
from ronda.relay.telegram import TelegramChannel, load_config, pair, save_config
from ronda.relay.webhook import Webhook, WebhookChannel, body_for, parse

CHAT = 4242
OTHER = 999


class FakeApi:
    def __init__(self, updates=None):
        self.calls = []
        self.updates = list(updates or [])
        self.next_id = 100

    async def call(self, method, **params):
        self.calls.append((method, params))
        if method == "sendMessage":
            self.next_id += 1
            return {"message_id": self.next_id, "chat": {"id": params["chat_id"]}}
        if method == "getUpdates":
            batch, self.updates = self.updates[:1], self.updates[1:]
            return batch[0] if batch else []
        return True

    def sent(self, method="sendMessage"):
        return [p for m, p in self.calls if m == method]


class FakeHub:
    def __init__(self, code=202, data=None):
        self.actions = []
        self.code, self.data = code, data or {"action": {}}

    async def post_action(self, session_id, body, channel):
        self.actions.append((session_id, body, channel))
        return self.code, self.data

    async def sessions(self):
        return [approval_session(), {**running_session(), "needs_you": False}]


def base(status, **kw):
    return {"session_id": "claude:s1", "source": "claude-code", "status": status, "needs_you": status != "running",
            "host": {"app": "orca", "confidence": 0.9}, "workspace": {"cwd": "D:\\code\\shop", "branch": "feat/x"},
            "capabilities": [], **kw}


def running_session():
    return base("running")


def approval_session(cmd="npm test", caps=("approve", "deny"), rid="p1"):
    return base("waiting_approval", capabilities=list(caps), request={"kind": "tool", "tool": "Bash", "input": cmd, "id": rid})


def reply_session(caps=("reply",), rid="s1"):
    return base("waiting_input", capabilities=list(caps), summary="Tests pass. Deploy?", request={"kind": "input", "id": rid})


def channel(api=None, hub=None):
    return TelegramChannel(api or FakeApi(), [CHAT], hub or FakeHub(), DEFAULT_RISKY)


def run(coro):
    return asyncio.run(coro)


def buttons(params):
    return [b["text"] for b in (params.get("reply_markup") or {}).get("inline_keyboard", [[]])[0]]


# --- Telegram: notifications ----------------------------------------------------

def test_approval_message_with_buttons_and_redaction():
    ch = channel()
    run(ch.on_change(running_session(), approval_session(cmd="TOKEN=abc123secret npm run deploy")))
    [msg] = ch.api.sent()
    assert msg["chat_id"] == CHAT
    assert msg["text"].startswith("Approval needed\nClaude Code in Orca, shop (feat/x)\nWants to run: TOKEN=<redacted>")
    assert "abc123secret" not in msg["text"]
    assert buttons(msg) == ["Approve", "Deny"]


def test_risky_command_offers_deny_only():
    ch = channel()
    run(ch.on_change(running_session(), approval_session(cmd="rm -rf build")))
    [msg] = ch.api.sent()
    assert buttons(msg) == ["Deny"] and "approve it on your computer" in msg["text"]


def test_no_buttons_without_capabilities_and_no_repeat():
    ch = channel()
    s = approval_session(caps=())
    run(ch.on_change(running_session(), s))
    run(ch.on_change(s, s))  # same status again: no second message
    [msg] = ch.api.sent()
    assert msg.get("reply_markup") is None


def test_relay_snapshot_is_not_news():
    ch = channel()
    relay = Relay([ch])
    run(relay.handle({"type": "snapshot", "sessions": [approval_session()]}))
    assert ch.api.sent() == []
    run(relay.handle({"type": "session", "session": running_session()}))
    run(relay.handle({"type": "session", "session": approval_session(rid="p2")}))
    assert len(ch.api.sent()) == 1


# --- Telegram: buttons ------------------------------------------------------------

def press(ch, verb, chat=CHAT):
    key = next(iter(ch.open))
    return {"update_id": 1, "callback_query": {"id": "cq1", "data": f"{verb}:{key}",
                                               "message": {"chat": {"id": chat}, "message_id": 101}}}


def test_approve_button_posts_action_and_closes_message():
    ch = channel()
    run(ch.on_change(running_session(), approval_session()))
    run(ch.handle_update(press(ch, "a")))
    assert ch.hub.actions == [("claude:s1", {"type": "approve", "request_id": "p1"}, "telegram")]
    [edit] = ch.api.sent("editMessageText")
    assert edit["text"].endswith("Approved from Telegram.") and edit["reply_markup"] == {"inline_keyboard": []}
    assert ch.open == {}


def test_button_from_unpaired_chat_is_ignored():
    ch = channel()
    run(ch.on_change(running_session(), approval_session()))
    run(ch.handle_update(press(ch, "a", chat=OTHER)))
    assert ch.hub.actions == [] and ch.api.sent("answerCallbackQuery") == []


def test_stale_button_and_hub_refusal():
    ch = channel(hub=FakeHub(code=409, data={"error": "not_waiting", "message": "The session is not waiting for an approval."}))
    run(ch.on_change(running_session(), approval_session()))
    run(ch.handle_update(press(ch, "d")))
    [answer] = ch.api.sent("answerCallbackQuery")
    assert answer["show_alert"] and "not waiting" in answer["text"]
    assert ch.api.sent("editMessageText")[0]["text"].endswith("Answered elsewhere.")
    run(ch.handle_update({"update_id": 2, "callback_query": {"id": "cq2", "data": "a:nope",
                                                             "message": {"chat": {"id": CHAT}}}}))
    assert ch.api.sent("answerCallbackQuery")[-1]["text"] == "This request is no longer open."


def test_answered_elsewhere_closes_the_message():
    ch = channel()
    run(ch.on_change(running_session(), approval_session()))
    run(ch.on_change(approval_session(), running_session()))
    assert ch.api.sent("editMessageText")[0]["text"].endswith("Answered elsewhere.") and ch.open == {}


# --- Telegram: replies ------------------------------------------------------------

def test_reply_by_replying_to_the_message():
    ch = channel()
    run(ch.on_change(running_session(), reply_session()))
    [msg] = ch.api.sent()
    assert msg["text"].endswith("Reply to this message to answer.")
    run(ch.handle_update({"update_id": 3, "message": {"message_id": 500, "chat": {"id": CHAT}, "text": "Yes, deploy.",
                                                      "reply_to_message": {"message_id": 101}}}))
    assert ch.hub.actions == [("claude:s1", {"type": "reply", "request_id": "s1", "text": "Yes, deploy."}, "telegram")]
    assert ch.api.sent()[-1]["text"] == "Sent."


def test_no_reply_hint_without_capability():
    ch = channel()
    run(ch.on_change(running_session(), reply_session(caps=())))
    assert "Reply to this message" not in ch.api.sent()[0]["text"] and ch.open == {}


def test_messages_from_unpaired_chats_get_nothing():
    ch = channel()
    run(ch.handle_update({"update_id": 4, "message": {"message_id": 1, "chat": {"id": OTHER}, "text": "/status"}}))
    assert ch.api.calls == []


def test_status_command():
    ch = channel()
    run(ch.handle_update({"update_id": 5, "message": {"message_id": 1, "chat": {"id": CHAT}, "text": "/status"}}))
    assert ch.api.sent()[0]["text"] == "Approval needed: Claude Code in Orca, shop (feat/x)"


# --- pairing ------------------------------------------------------------------------

def test_pairing_accepts_only_the_code():
    def msg(uid, text, chat=CHAT):
        return {"update_id": uid, "message": {"chat": {"id": chat, "username": "me"}, "text": text}}
    api = FakeApi(updates=[[msg(1, "/pair 000000")], [msg(2, "/pair 111111", chat=OTHER), msg(3, "/pair 123456")]])
    chat, name = run(pair(api, "123456"))
    assert (chat, name) == (CHAT, "me")
    assert api.sent()[-1]["chat_id"] == CHAT


def test_pairing_times_out():
    t = iter(range(0, 1000, 200))
    with pytest.raises(TimeoutError):
        run(pair(FakeApi(), "123456", deadline_s=300, clock=lambda: next(t)))


def test_config_roundtrip(tmp_path):
    assert load_config(tmp_path) is None
    save_config(tmp_path, "123:abc", [CHAT], "ronda_bot")
    assert load_config(tmp_path)["chats"] == [CHAT]


# --- webhooks -------------------------------------------------------------------------

def test_webhook_config_validation():
    hooks, errors = parse([{"url": "https://ntfy.sh/t", "format": "text"}, {"url": "http://example.com"},
                           {"url": "http://localhost:9000/x"}, {"url": "https://x", "format": "xml"}])
    assert [h.url for h in hooks] == ["https://ntfy.sh/t", "http://localhost:9000/x"]
    assert [e.index for e in errors] == [1, 3]


def test_webhook_formats_are_redacted():
    s = approval_session(cmd="curl -H 'Authorization: Bearer abcdefgh12345' https://x")
    body, ctype = body_for(Webhook(url="https://x"), s)
    data = json.loads(body)
    assert data["type"] == "session.status" and data["status"] == "waiting_approval" and "abcdefgh12345" not in body.decode()
    text, ctype = body_for(Webhook(url="https://x", format="text"), s)
    assert text.decode().startswith("Approval needed: Claude Code in Orca") and ctype.startswith("text/plain")
    slack, _ = body_for(Webhook(url="https://x", format="slack"), s)
    assert json.loads(slack)["text"].startswith("*Approval needed*")


def test_webhook_signed_and_retried():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(500 if len(seen) == 1 else 200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def no_sleep(_):
        return None

    ch = WebhookChannel([Webhook(url="https://hooks.example/x", secret="k")], client=client, sleep=no_sleep)
    ok = run(ch.send(ch.hooks[0], approval_session()))
    assert ok and len(seen) == 2
    req = seen[-1]
    assert req.headers["X-Ronda-Signature"] == "sha256=" + hmac.new(b"k", req.content, hashlib.sha256).hexdigest()


def test_webhook_fires_on_the_notification_rule_only():
    seen = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(204)))

    async def go():
        ch = WebhookChannel([Webhook(url="https://hooks.example/x", statuses=("error",))], client=client)
        await ch.on_change(running_session(), approval_session())   # status not subscribed
        await ch.on_change(running_session(), base("error", summary="rate_limit"))
        await asyncio.gather(*ch.tasks)

    run(go())
    assert len(seen) == 1 and json.loads(seen[0].content)["status"] == "error"


# --- integration: real hub, real stream and action API, fake Telegram ------------

def test_relay_against_a_live_hub(tmp_path):
    from ronda.config import Settings
    from ronda.relay.common import HubClient
    from tests.test_hook_actions import TOKEN, Hub

    with Hub(tmp_path, Settings()) as hub:
        async def go():
            client = HubClient(f"http://127.0.0.1:{hub.port}", TOKEN)
            ch = TelegramChannel(FakeApi(), [CHAT], client, DEFAULT_RISKY)
            relay = Relay([ch])
            stream = client.stream()
            await relay.handle(await stream.__anext__())  # snapshot
            ev = {"event_id": "p1", "ts": "2099-01-01T00:00:00+00:00", "source": "claude-code",
                  "session_id": "claude:s1", "status": "waiting_approval", "capabilities": ["approve", "deny"],
                  "request": {"kind": "tool", "tool": "Bash", "input": "npm test", "id": "p1"}}
            await asyncio.to_thread(hub.call, "POST", "/v1/events", ev)
            await relay.handle(await asyncio.wait_for(stream.__anext__(), 5))
            assert buttons(ch.api.sent()[0]) == ["Approve", "Deny"]
            await ch.handle_update(press(ch, "a"))
            await stream.aclose()
            await client.client.aclose()

        run(go())
        [a] = hub.app.state.store.actions("claude:s1")
        assert a["type"] == "approve" and a["channel"] == "telegram" and a["request_id"] == "p1"


def test_cli_pair_and_unpair(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from ronda.cli import app
    import ronda.relay.telegram as tg

    monkeypatch.setenv("RONDA_HOME", str(tmp_path))

    async def fake_call(self, method, **params):
        return {"username": "ronda_bot"}

    async def fake_pair(api, code, **kw):
        assert len(code) == 6 and code.isdigit()
        return CHAT, "me"

    monkeypatch.setattr(tg.TelegramApi, "call", fake_call)
    monkeypatch.setattr(tg, "pair", fake_pair)
    r = CliRunner().invoke(app, ["pair", "telegram"], input="123:secret-token\n")
    assert r.exit_code == 0, r.output
    assert "secret-token" not in r.output and "Paired with me" in r.output
    assert load_config(tmp_path)["chats"] == [CHAT]
    r = CliRunner().invoke(app, ["unpair", "telegram"])
    assert r.exit_code == 0 and load_config(tmp_path) is None
