"""M2: actions API, long-poll for hooks, audit, notifications (ADR-0008..0010)."""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ronda.config import Settings
from ronda.hub.app import create_app
from ronda.hub.notify import Notifier, should_notify
from ronda.schema import Status

TOKEN = "t" * 43
BASE = "http://127.0.0.1:7878"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
T0 = datetime.now(timezone.utc)
SID = "claude:s1"


def ev(i, status, at=None, **kw):
    return {"event_id": f"e{i}", "ts": (T0 + timedelta(seconds=at if at is not None else i)).isoformat(),
            "source": "claude-code", "session_id": SID, "status": status, **kw}


def ask_approval(i, cmd="npm test", rid=None):
    return ev(i, "waiting_approval", capabilities=["approve", "deny", "reply"],
              request={"kind": "tool", "tool": "Bash", "input": cmd, "id": rid or f"e{i}"})


def ask_reply(i, rid=None):
    return ev(i, "waiting_input", capabilities=["approve", "deny", "reply"], request={"kind": "input", "id": rid or f"e{i}"})


@pytest.fixture
def sent_notes():
    return []


@pytest.fixture
def client(tmp_path, sent_notes):
    app = create_app(home=tmp_path, port=7878, token=TOKEN, settings=Settings(),
                     notifier=Notifier(sender=lambda t, b: sent_notes.append((t, b)), min_gap_s=0))
    with TestClient(app, base_url=BASE) as c:
        yield c


def post(client, *events):
    r = client.post("/v1/events", headers=AUTH, json=list(events))
    assert r.status_code == 202, r.text


def act(client, **body):
    return client.post(f"/v1/sessions/{SID}/actions", headers=AUTH, json=body)


def poll(client, for_, rid, wait=0):
    r = client.get(f"/v1/sessions/{SID}/actions/next", headers=AUTH, params={"for": for_, "request_id": rid, "wait": wait})
    assert r.status_code == 200, r.text
    return r.json()


# --- validation ---------------------------------------------------------------

def test_approve_then_hook_receives_it_once(client):
    post(client, ev(1, "running"), ask_approval(2))
    r = act(client, type="approve", request_id="e2")
    assert r.status_code == 202 and r.json()["action"]["outcome"] == "pending"
    got = poll(client, "approval", "e2")
    assert got["action"]["type"] == "approve" and got["action"]["outcome"] == "delivered"
    assert got["action"]["channel"] == "api"
    assert poll(client, "approval", "e2") == {"action": None, "reason": "timeout"}


def test_request_id_defaults_to_the_pending_one(client):
    post(client, ask_approval(1))
    assert act(client, type="deny").status_code == 202
    assert poll(client, "approval", "e1")["action"]["type"] == "deny"


@pytest.mark.parametrize("events, body, code, error", [
    ([ev(1, "running")], {"type": "approve"}, 409, "not_waiting"),
    ([ask_reply(1)], {"type": "approve"}, 409, "not_waiting"),
    ([ask_approval(1)], {"type": "reply", "text": "hi"}, 409, "not_waiting"),
    ([ask_reply(1)], {"type": "reply", "text": "   "}, 422, "empty_reply"),
    ([ask_approval(1)], {"type": "approve", "request_id": "old"}, 409, "stale_request"),
    ([ev(1, "waiting_approval", request={"kind": "tool", "tool": "Bash", "input": "ls", "id": "e1"})],
     {"type": "approve"}, 409, "not_supported"),  # the pos did not offer approve (FR-25)
])
def test_refusals(client, events, body, code, error):
    post(client, *events)
    r = act(client, **body)
    assert r.status_code == code and r.json()["error"] == error


def test_unknown_session_is_404(client):
    assert client.post("/v1/sessions/claude:nope/actions", headers=AUTH, json={"type": "approve"}).status_code == 404


def test_risky_command_needs_confirmation(client):
    post(client, ask_approval(1, cmd="rm -rf build/"))
    r = act(client, type="approve")
    assert r.status_code == 409 and r.json()["error"] == "confirm_required"
    assert act(client, type="deny").status_code == 202  # denying is never gated
    assert act(client, type="approve", confirm=True).status_code == 202


def test_approvals_off(tmp_path):
    app = create_app(home=tmp_path, port=7878, token=TOKEN, settings=Settings(approval_wait_s=0),
                     notifier=Notifier(enabled=False))
    with TestClient(app, base_url=BASE) as c:
        post(c, ask_approval(1))
        assert act(c, type="approve").json()["error"] == "approvals_off"


def test_reply(client):
    post(client, ev(1, "running"), ask_reply(2))
    assert act(client, type="reply", text="  Stop here, I'll review.  ").status_code == 202
    got = poll(client, "reply", "e2")["action"]
    assert got["text"] == "Stop here, I'll review."


# --- long-poll ----------------------------------------------------------------

def test_poll_resolves_when_the_session_moves_on(client):
    post(client, ask_approval(1))
    result = {}

    def hook():
        result.update(poll(client, "approval", "e1", wait=10))

    th = threading.Thread(target=hook)
    t = time.monotonic()
    th.start()
    time.sleep(0.3)
    post(client, ev(2, "running"))  # answered in the terminal: PostToolUse
    th.join(5)
    assert result == {"action": None, "reason": "resolved"}
    assert time.monotonic() - t < 3


def test_poll_wakes_on_action(client):
    post(client, ask_reply(1))
    result = {}
    th = threading.Thread(target=lambda: result.update(poll(client, "reply", "e1", wait=10)))
    th.start()
    time.sleep(0.3)
    act(client, type="reply", text="go on")
    th.join(5)
    assert result["action"]["text"] == "go on"


def test_stale_actions_expire_in_audit(client):
    post(client, ask_approval(1))
    act(client, type="approve")
    post(client, ev(2, "running"))
    audit = client.get(f"/v1/sessions/{SID}/actions", headers=AUTH).json()["actions"]
    assert [a["outcome"] for a in audit] == ["expired"]
    assert client.get("/v1/actions", headers=AUTH).json()["actions"][0]["session_id"] == SID


def test_web_channel_via_cookie(client):
    post(client, ask_approval(1))
    client.get(f"/?login={client.app.state.login_codes.issue()}", follow_redirects=False)
    r = client.post(f"/v1/sessions/{SID}/actions", json={"type": "deny"}, headers={"Origin": BASE})
    assert r.status_code == 202 and r.json()["action"]["channel"] == "web"


def test_action_is_broadcast(client):
    post(client, ask_approval(1))
    with client.websocket_connect("ws://127.0.0.1:7878/v1/stream", headers=AUTH) as ws:
        ws.receive_json()
        act(client, type="deny")
        msg = ws.receive_json()
        assert msg["type"] == "action" and msg["action"]["type"] == "deny"


# --- notifications (ADR-0009) -----------------------------------------------------

@pytest.mark.parametrize("prev, new, expected", [
    (None, Status.waiting_input, False),           # fresh session
    (Status.running, Status.waiting_input, True),  # finished turn
    (Status.running, Status.waiting_approval, True),
    (Status.waiting_approval, Status.waiting_approval, False),
    (Status.running, Status.error, True),
    (Status.waiting_input, Status.running, False),
    (Status.running, Status.ended, False),
    (Status.done, Status.waiting_input, True),        # an idle OpenBot agent asks a question
])
def test_should_notify(prev, new, expected):
    assert should_notify(prev, new) is expected


def test_notification_text_has_no_tool_input(client, sent_notes):
    post(client, ev(1, "running", workspace={"cwd": "/home/u/shop"}, host={"app": "orca", "confidence": 0.9}),
         ask_approval(2, cmd="export TOKEN=hunter2"))
    time.sleep(0.2)
    assert sent_notes == [("Approval needed", "claude-code in Orca, shop".replace("claude-code", "Claude Code"))]
    assert "hunter2" not in repr(sent_notes)


def test_risky_approve_never_from_telegram(client):
    post(client, ask_approval(1, cmd="git push --force"))
    r = client.post(f"/v1/sessions/{SID}/actions", headers={**AUTH, "X-Ronda-Channel": "telegram"},
                    json={"type": "approve", "confirm": True})
    assert r.status_code == 409 and r.json()["error"] == "risky_remote"
    r = client.post(f"/v1/sessions/{SID}/actions", headers={**AUTH, "X-Ronda-Channel": "telegram"}, json={"type": "deny"})
    assert r.status_code == 202 and r.json()["action"]["channel"] == "telegram"
