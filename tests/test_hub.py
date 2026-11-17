import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sekantor.hub.app import create_app, run_sweep
from sekantor.schema import Event

TOKEN = "t" * 43
BASE = "http://127.0.0.1:7878"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime.now(timezone.utc)


def ev(i, status, sid="claude:a", at=0, **kw):
    return {"event_id": f"e{i}", "ts": (NOW + timedelta(seconds=at or i)).isoformat(), "source": "claude-code",
            "session_id": sid, "status": status, **kw}


@pytest.fixture
def client(tmp_path):
    app = create_app(home=tmp_path, port=7878, token=TOKEN)
    with TestClient(app, base_url=BASE) as c:
        yield c


# --- auth ---------------------------------------------------------------------

def test_every_route_needs_the_token(client):
    for path in ["/", "/v1/health", "/v1/sessions", "/index.html"]:
        assert client.get(path).status_code == 401, path
    assert client.post("/v1/events", json=ev(1, "running")).status_code == 401
    assert client.get("/v1/health", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_bearer_token_works(client):
    r = client.get("/v1/health", headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_foreign_host_header_refused(client):
    r = client.get("/v1/health", headers={**AUTH, "Host": "evil.example:7878"})
    assert r.status_code == 403


def test_login_code_sets_cookie_once(client):
    code = client.app.state.login_codes.issue()
    r = client.get(f"/?login={code}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=Strict" in r.headers["set-cookie"]
    assert client.get("/v1/sessions").status_code == 200  # cookie now set
    client.cookies.clear()
    assert client.get(f"/?login={code}", follow_redirects=False).status_code == 401  # spent
    assert client.get(f"/?token={TOKEN}", follow_redirects=False).status_code == 401  # the token never works in a URL


def test_login_code_endpoint_is_bearer_only(client):
    r = client.post("/v1/login-code", headers=AUTH)
    assert r.status_code == 200 and r.json()["path"].startswith("/?login=")
    client.get(f"/?login={client.app.state.login_codes.issue()}", follow_redirects=False)
    assert client.post("/v1/login-code", headers={"Origin": BASE}).status_code == 403


def test_shutdown_needs_the_bearer_token(client):
    client.get(f"/?login={client.app.state.login_codes.issue()}", follow_redirects=False)
    assert client.post("/v1/shutdown", headers={"Origin": BASE}).status_code == 403
    client.cookies.clear()
    assert client.post("/v1/shutdown").status_code == 401
    assert client.app.state.should_exit is False


def test_shutdown_sets_should_exit(client):
    assert client.app.state.should_exit is False
    r = client.post("/v1/shutdown", headers=AUTH)
    assert r.status_code == 202 and r.json() == {"stopping": True}
    assert client.app.state.should_exit is True


def test_cookie_post_needs_same_origin(client):
    client.get(f"/?login={client.app.state.login_codes.issue()}", follow_redirects=False)
    assert client.post("/v1/events", json=ev(1, "running")).status_code == 403
    assert client.post("/v1/events", json=ev(1, "running"), headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/v1/events", json=ev(1, "running"), headers={"Origin": BASE}).status_code == 202


# --- API ----------------------------------------------------------------------

def test_post_and_list_in_inbox_order(client):
    r = client.post("/v1/events", headers=AUTH, json=[
        ev(1, "running", sid="claude:run"),
        ev(2, "waiting_input", sid="claude:input"),
        ev(3, "waiting_approval", sid="claude:appr",
           request={"kind": "tool", "tool": "Bash", "input": "docker compose up -d"}),
    ])
    assert r.json() == {"accepted": 3, "duplicates": 0}
    sessions = client.get("/v1/sessions", headers=AUTH).json()["sessions"]
    assert [s["session_id"] for s in sessions] == ["claude:appr", "claude:input", "claude:run"]
    assert sessions[0]["needs_you"] is True and sessions[0]["request"]["input"] == "docker compose up -d"
    only = client.get("/v1/sessions?status=running", headers=AUTH).json()["sessions"]
    assert [s["session_id"] for s in only] == ["claude:run"]


def test_duplicates_and_validation(client):
    client.post("/v1/events", headers=AUTH, json=ev(1, "running"))
    assert client.post("/v1/events", headers=AUTH, json=ev(1, "running")).json()["duplicates"] == 1
    assert client.post("/v1/events", headers=AUTH, json={"nope": 1}).status_code == 422
    assert client.post("/v1/events", headers=AUTH, json=[ev(i, "running") for i in range(101)]).status_code == 413


def test_timeline(client):
    client.post("/v1/events", headers=AUTH, json=[ev(i, "running") for i in range(1, 4)])
    evs = client.get("/v1/sessions/claude:a/events?limit=2", headers=AUTH).json()["events"]
    assert [e["event_id"] for e in evs] == ["e2", "e3"]
    assert client.get("/v1/sessions/claude:none/events", headers=AUTH).status_code == 404


# --- WebSocket ------------------------------------------------------------------

def test_stream_snapshot_then_updates(client):
    client.post("/v1/events", headers=AUTH, json=ev(1, "running"))
    with client.websocket_connect("ws://127.0.0.1:7878/v1/stream", headers=AUTH) as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["sessions"][0]["status"] == "running"
        client.post("/v1/events", headers=AUTH, json=ev(2, "waiting_input", summary="Your turn"))
        msg = ws.receive_json()
        assert msg["type"] == "session" and msg["session"]["status"] == "waiting_input"
        assert msg["event"]["event_id"] == "e2"


def test_stream_requires_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1:7878/v1/stream") as ws:
            ws.receive_json()


def test_stream_cookie_needs_origin(client):
    client.get(f"/?login={client.app.state.login_codes.issue()}", follow_redirects=False)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1:7878/v1/stream", headers={"Origin": "http://evil.example"}) as ws:
            ws.receive_json()
    with client.websocket_connect("ws://127.0.0.1:7878/v1/stream", headers={"Origin": BASE}) as ws:
        assert ws.receive_json()["type"] == "snapshot"


# --- FR-07 sweep ----------------------------------------------------------------

def test_sweep_ends_silent_dead_sessions(client):
    app = client.app
    old = (NOW - timedelta(minutes=20)).isoformat()
    client.post("/v1/events", headers=AUTH, json=[
        {**ev(1, "waiting_input", sid="claude:dead"), "ts": old, "process": {"pid": 2_000_000_000}},
        {**ev(2, "waiting_input", sid="claude:fresh")},
    ])
    assert len(run_sweep(app.state.store)) == 1
    by_id = {s["session_id"]: s for s in client.get("/v1/sessions", headers=AUTH).json()["sessions"]}
    assert by_id["claude:dead"]["status"] == "ended"
    assert by_id["claude:fresh"]["status"] == "waiting_input"


def test_sweep_leaves_an_event_in_the_timeline(client):
    old = (NOW - timedelta(minutes=20)).isoformat()
    client.post("/v1/events", headers=AUTH, json={**ev(1, "waiting_input", sid="claude:gone"), "ts": old,
                                                  "process": {"pid": 2_000_000_000}})
    run_sweep(client.app.state.store)
    evs = client.get("/v1/sessions/claude:gone/events", headers=AUTH).json()["events"]
    assert evs[-1]["type"] == "session_ended" and evs[-1]["status"] == "ended"


def test_swept_session_reaches_a_waiting_stream_client(tmp_path):
    """The sweep runs in a worker thread; what it ends must still reach WS clients safely."""
    import asyncio

    from sekantor.hub.app import sweep_tick
    from sekantor.hub.store import Store
    from sekantor.hub.stream import Broadcaster
    from sekantor.schema import Event

    store = Store(tmp_path / "sekantor.db")
    old = (NOW - timedelta(minutes=20)).isoformat()
    store.add_event(Event.model_validate({**ev(1, "waiting_input", sid="claude:gone"), "ts": old,
                                          "process": {"pid": 2_000_000_000}}))
    broadcaster = Broadcaster()

    async def main():
        client = asyncio.Queue()
        broadcaster._queues.add(client)
        waiting = asyncio.create_task(client.get())
        await asyncio.sleep(0)
        await sweep_tick(store, broadcaster)
        return await asyncio.wait_for(waiting, 2)

    import threading

    got = []
    # debug mode rejects loop calls from other threads; a lost wakeup would hang, so bound it
    t = threading.Thread(target=lambda: got.append(asyncio.run(main(), debug=True)), daemon=True)
    t.start()
    t.join(10)
    store.close()
    assert got, "the stream client never got the swept session"
    assert got[0]["session"]["session_id"] == "claude:gone" and got[0]["session"]["status"] == "ended"


def test_a_failing_sweep_is_logged(tmp_path, monkeypatch, caplog):
    import time

    import sekantor.hub.app as hub_app

    def broken(store, now=None):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(hub_app, "SWEEP_EVERY_S", 0.01)
    monkeypatch.setattr(hub_app, "run_sweep", broken)
    app = create_app(home=tmp_path, port=7878, token=TOKEN)
    with TestClient(app, base_url=BASE):
        time.sleep(0.3)
    assert any("sweep failed" in r.getMessage() and r.exc_info for r in caplog.records)


def test_actions_routes_are_gone(client):
    assert client.post("/v1/sessions/x/actions", json={"type": "approve"}, headers=AUTH).status_code in (404, 405)
    assert client.get("/v1/sessions/x/actions/next?request_id=r&for=approval", headers=AUTH).status_code == 404
    assert client.get("/v1/actions", headers=AUTH).status_code == 404


def test_an_old_event_with_capabilities_is_accepted(client):
    e = ev(1, "waiting_approval", capabilities=["approve", "deny"], request={"kind": "tool", "id": "r1"})
    assert client.post("/v1/events", json=e, headers=AUTH).status_code == 202


# --- POST /v1/hooks/claude: the raw hook payload from the native forwarder ------------

HOOK_ID = "0123456789abcdef01234567"
HOOK_TS = "2026-11-17T01:02:03+00:00"
PRE_TOOL = {"hook_event_name": "PreToolUse", "session_id": "abc", "cwd": "/work/proj", "tool_name": "Bash",
            "tool_input": {"command": "ls"}}


def hook_body(payload=None, env=None, **kw):
    return {"v": 1, "id": HOOK_ID, "ts": HOOK_TS, "payload": payload or PRE_TOOL, "env": env or {}, **kw}


def test_hook_endpoint_stores_what_the_python_hook_builds(client):
    from sekantor.pos.claude_code import hook

    env = {"CLAUDE_PID": str(os.getpid()), "CLAUDE_CODE_ENTRYPOINT": "claude-vscode"}
    r = client.post("/v1/hooks/claude", headers=AUTH, json=hook_body(env=env))
    assert r.status_code == 202 and r.json() == {"stored": True, "event_id": HOOK_ID}
    want = hook.build_event(PRE_TOOL, env, event_id=HOOK_ID, ts=HOOK_TS)
    got = client.get("/v1/sessions/claude:abc/events", headers=AUTH).json()["events"]
    assert len(got) == 1
    assert got[0] == Event.model_validate(want).model_dump(mode="json", exclude_none=True)
    assert got[0]["event_id"] == HOOK_ID and got[0]["process"] == {"pid": os.getpid()}
    assert got[0]["host"]["app"] == "vscode"


def test_hook_endpoint_drops_ignored_cwd(client):
    p = {**PRE_TOOL, "cwd": "C:/Users/x/AppData/Local/Programs/OpenBot/helper"}
    r = client.post("/v1/hooks/claude", headers=AUTH, json=hook_body(p))
    assert r.status_code == 202 and r.json() == {"stored": False}
    assert client.app.state.store.sessions() == []


def test_hook_endpoint_ignores_events_with_no_translation(client):
    p = {"hook_event_name": "SubagentStop", "session_id": "abc", "cwd": "/w"}
    r = client.post("/v1/hooks/claude", headers=AUTH, json=hook_body(p))
    assert r.status_code == 202 and r.json() == {"stored": False}


def test_hook_endpoint_needs_the_bearer_token(client):
    code = client.app.state.login_codes.issue()
    client.get(f"/?login={code}", follow_redirects=False)  # the client now carries the cookie
    r = client.post("/v1/hooks/claude", json=hook_body(), headers={"Origin": BASE})
    assert r.status_code == 403
    assert client.app.state.store.sessions() == []


@pytest.mark.parametrize("body", [
    {"v": 1, "id": HOOK_ID, "ts": HOOK_TS, "payload": [], "env": {}},
    {"v": 1, "id": HOOK_ID, "ts": HOOK_TS, "payload": {"a": 1}, "env": {"A": 1}},
    {"v": 1, "id": "", "ts": HOOK_TS, "payload": {"a": 1}, "env": {}},
    {"v": 1, "id": HOOK_ID, "ts": "yesterday", "payload": {"a": 1}, "env": {}},
    {"v": 2, "id": HOOK_ID, "ts": HOOK_TS, "payload": {"a": 1}, "env": {}},
    {"id": HOOK_ID},
    [1, 2],
    "text",
])
def test_hook_endpoint_malformed_body_is_422(client, body):
    assert client.post("/v1/hooks/claude", headers=AUTH, json=body).status_code == 422


def test_hook_endpoint_not_json_is_422(client):
    r = client.post("/v1/hooks/claude", headers={**AUTH, "Content-Type": "application/json"}, content=b"\xff\xfe{")
    assert r.status_code == 422


def test_hook_endpoint_huge_payload_is_413(client):
    big = {**PRE_TOOL, "tool_input": {"text": "x" * (4 * 1024 * 1024 + 10)}}
    assert client.post("/v1/hooks/claude", headers=AUTH, json=hook_body(big)).status_code == 413


def test_hook_endpoint_session_start_schedules_the_deep_follow_up(client, monkeypatch):
    import threading

    calls, done = [], threading.Event()

    def collect(pid, deep, **kw):
        calls.append((pid, deep))
        if not deep:
            return [], None, None
        done.set()
        return ["zsh", "Code.exe"], "/x/Code.exe", None

    monkeypatch.setattr("sekantor.pos.claude_code.fingerprint.collect", collect)
    start = {"hook_event_name": "SessionStart", "session_id": "abc", "cwd": "/w", "source": "startup"}
    r = client.post("/v1/hooks/claude", headers=AUTH, json=hook_body(start, env={"CLAUDE_PID": "4242"}))
    assert r.status_code == 202
    assert done.wait(5)
    for _ in range(100):
        if len(client.get("/v1/sessions/claude:abc/events", headers=AUTH).json()["events"]) == 2:
            break
        time.sleep(0.05)
    events = client.get("/v1/sessions/claude:abc/events", headers=AUTH).json()["events"]
    assert len(events) == 2 and (4242, True) in calls
    assert events[0]["type"] == "message" or events[1]["type"] == "message"


def test_hook_endpoint_other_events_do_not_run_the_deep_collector(client, monkeypatch):
    def collect(pid, deep, **kw):
        assert not deep
        return [], None, None

    monkeypatch.setattr("sekantor.pos.claude_code.fingerprint.collect", collect)
    assert client.post("/v1/hooks/claude", headers=AUTH, json=hook_body()).status_code == 202


def test_hook_env_file_lists_rule_env_names_and_claude_pid(tmp_path):
    from sekantor.hub.app import create_app
    from sekantor.pos.claude_code.fingerprint import load_rules

    create_app(home=tmp_path, port=7878, token=TOKEN)
    names = (tmp_path / "hook-env.txt").read_text(encoding="utf-8").split("\n")
    assert names[-1] == "" and names[:-1] == sorted(set(names[:-1]))
    want = {s["env"] for h in load_rules()["hosts"] for s in h["signals"] if "env" in s}
    want |= {s["env"] for s in load_rules()["fallback"]["terminal"]["signals"] if "env" in s}
    assert set(names[:-1]) == want | {"CLAUDE_PID"}
    assert "CLAUDE_CODE_ENTRYPOINT" in names and "ANTHROPIC_API_KEY" not in names


def test_setup_endpoint_matches_setup_json(client):
    from typer.testing import CliRunner

    from sekantor.cli import app as cli_app

    assert client.get("/v1/setup").status_code == 401
    r = client.get("/v1/setup", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == json.loads(CliRunner().invoke(cli_app, ["setup", "--json"]).stdout)


def test_setup_endpoint_refuses_cookie(client):
    code = client.app.state.login_codes.issue()
    client.get(f"/?login={code}", follow_redirects=False)
    assert client.get("/v1/setup").status_code == 403


@pytest.mark.parametrize("cwd", [5, ["/w"], {"a": 1}])
def test_hook_endpoint_non_string_cwd_is_422(client, cwd):
    r = client.post("/v1/hooks/claude", headers=AUTH, json=hook_body({**PRE_TOOL, "cwd": cwd}))
    assert r.status_code == 422


def test_hook_endpoint_duplicate_id_is_not_stored_twice_nor_followed_up(client, monkeypatch):
    calls = []

    def collect(pid, deep, **kw):
        calls.append(deep)
        return [], None, None

    monkeypatch.setattr("sekantor.pos.claude_code.fingerprint.collect", collect)
    start = {"hook_event_name": "SessionStart", "session_id": "abc", "cwd": "/w", "source": "startup"}
    first = client.post("/v1/hooks/claude", headers=AUTH, json=hook_body(start, env={"CLAUDE_PID": "1"}))
    for _ in range(100):
        if True in calls:
            break
        time.sleep(0.05)
    again = client.post("/v1/hooks/claude", headers=AUTH, json=hook_body(start, env={"CLAUDE_PID": "1"}))
    time.sleep(0.5)
    assert first.json()["stored"] is True and again.status_code == 202 and again.json() == {"stored": False}
    assert calls.count(True) == 1
