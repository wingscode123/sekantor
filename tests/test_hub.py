from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sekantor.hub.app import create_app, run_sweep

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
