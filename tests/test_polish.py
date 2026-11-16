"""FR-14 open in source, FR-15 snooze, FR-33 quiet hours."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ronda.config import Settings, in_quiet_hours, parse_quiet_hours
from ronda.hub import opener
from ronda.hub.app import create_app
from ronda.hub.notify import Notifier
from ronda.hub.status import SessionState
from ronda.schema import Event, Host, Status, Workspace

TOKEN = "t" * 43
BASE = "http://127.0.0.1:7878"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime.now(timezone.utc)


def state(app=None, sid="claude:s1", cwd=None, status=Status.waiting_input):
    return SessionState(session_id=sid, source="claude-code", status=status, status_since=NOW, status_ts=NOW,
                        started_at=NOW, last_event_at=NOW, workspace=Workspace(cwd=cwd),
                        host=Host(app=app, confidence=1.0) if app else None)


# --- FR-14 ------------------------------------------------------------------------

def test_open_plans(tmp_path):
    d = str(tmp_path)
    p = opener.plan(state("vscode", cwd=d))
    assert p.label == "Open in VS Code" and p.kind == "url" and p.target.startswith("vscode://file/")
    assert opener.plan(state("cursor", cwd=d)).target.startswith("cursor://file/")
    p = opener.plan(state("tmux", sid="tmux:%3:123"), which=lambda c: "/usr/bin/tmux")
    assert p.target[:4] == ["tmux", "switch-client", "-t", "%3"]
    p = opener.plan(state("terminal", cwd=d))
    assert (p.label, p.kind, p.target) == ("Open folder", "folder", d)
    assert opener.plan(state("terminal", cwd=str(tmp_path / "gone"))) is None
    assert opener.plan(state(None)) is None


def test_open_orca(monkeypatch, tmp_path):
    monkeypatch.setattr(opener, "_orca_cli", lambda: "orca")
    p = opener.plan(state("orca", sid="orca:term_a:99"))
    assert p.target == ["orca", "terminal", "switch", "--terminal", "term_a", "--json"]
    p = opener.plan(state("orca", cwd=str(tmp_path)))
    assert p.target[:4] == ["orca", "worktree", "activate", "--worktree"]


def test_vscode_url_has_no_injection(tmp_path):
    weird = tmp_path / "a b&c;calc"
    weird.mkdir()
    p = opener.plan(state("vscode", cwd=str(weird)))
    assert " " not in p.target and "&" not in p.target and ";" not in p.target


# --- API ------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app(home=tmp_path, port=7878, token=TOKEN, settings=Settings(), notifier=Notifier(enabled=False))
    opened = []
    monkeypatch.setattr(opener, "run", opened.append)
    with TestClient(app, base_url=BASE) as c:
        c.opened = opened
        c.cwd = str(tmp_path)
        yield c


def post(c, **kw):
    ev = {"event_id": kw.pop("eid", "e1"), "ts": NOW.isoformat(), "source": "claude-code", "session_id": "claude:s1",
          "status": "waiting_input", **kw}
    assert c.post("/v1/events", headers=AUTH, json=ev).status_code == 202


def test_open_endpoint(client):
    post(client, host={"app": "vscode", "confidence": 1}, workspace={"cwd": client.cwd})
    s = client.get("/v1/sessions", headers=AUTH).json()["sessions"][0]
    assert s["open_label"] == "Open in VS Code"
    r = client.post("/v1/sessions/claude:s1/open", headers=AUTH)
    assert r.status_code == 200 and r.json() == {"opened": "Open in VS Code"}
    assert client.opened[0].kind == "url"
    r = client.post("/v1/sessions/claude:s1/open", headers={**AUTH, "X-Ronda-Channel": "telegram"})
    assert r.status_code == 403


def test_open_unknown_is_409(client):
    post(client)
    assert client.post("/v1/sessions/claude:s1/open", headers=AUTH).json()["error"] == "cannot_open"


def test_snooze_and_unsnooze(client):
    post(client)
    r = client.post("/v1/sessions/claude:s1/snooze", headers=AUTH, json={"minutes": 30})
    until = datetime.fromisoformat(r.json()["snoozed_until"])
    assert timedelta(minutes=29) < until - datetime.now(timezone.utc) <= timedelta(minutes=30)
    assert client.get("/v1/sessions", headers=AUTH).json()["sessions"][0]["snoozed_until"]
    post(client, eid="e2", status="running")  # new events keep the snooze
    assert client.get("/v1/sessions", headers=AUTH).json()["sessions"][0]["snoozed_until"]
    client.post("/v1/sessions/claude:s1/snooze", headers=AUTH, json={"minutes": None})
    assert client.delete("/v1/sessions/claude:s1/snooze", headers=AUTH).json() == {"snoozed_until": None}
    assert client.post("/v1/sessions/claude:none/snooze", headers=AUTH, json={}).status_code == 404


def test_snooze_keeps_an_event_that_lands_meanwhile(client, monkeypatch):
    """An event that arrives while the snooze is being saved must not be overwritten."""
    import threading

    post(client)
    store = client.app.state.store
    get = store._get_session
    writer = []

    def get_while_an_event_arrives(sid):
        s = get(sid)
        if not writer:  # the snooze's read: another request stores an event now
            ev = Event(event_id="e2", ts=NOW + timedelta(seconds=1), source="claude-code", session_id=sid,
                       status=Status.running, summary="new work")
            writer.append(threading.Thread(target=store.add_event, args=(ev,)))
            writer[0].start()
            writer[0].join(0.2)
        return s

    monkeypatch.setattr(store, "_get_session", get_while_an_event_arrives)
    assert client.post("/v1/sessions/claude:s1/snooze", headers=AUTH, json={"minutes": 30}).status_code == 200
    writer[0].join(5)
    monkeypatch.setattr(store, "_get_session", get)
    s = client.get("/v1/sessions", headers=AUTH).json()["sessions"][0]
    assert s["status"] == "running" and s["summary"] == "new work" and s["snoozed_until"]


# --- notifications gated --------------------------------------------------------------

def test_snoozed_session_is_not_notified():
    sent = []
    n = Notifier(sender=lambda t, b: sent.append(t), min_gap_s=0)
    prev = state(status=Status.running)
    new = state(status=Status.waiting_approval)
    new.snoozed_until = NOW + timedelta(hours=1)
    assert n.maybe(prev, new) is False
    new.snoozed_until = NOW - timedelta(minutes=1)  # expired
    assert n.maybe(prev, new) is True


def test_quiet_hours():
    assert parse_quiet_hours("22:00-07:00") == (1320, 420)
    assert parse_quiet_hours("09:30-17:00") == (570, 1020)
    for bad in ("", None, "25:00-01:00", "10:00-10:00", "nonsense"):
        assert parse_quiet_hours(bad) is None
    night = parse_quiet_hours("22:00-07:00")
    local = datetime.now().astimezone().tzinfo
    assert in_quiet_hours(night, datetime(2026, 1, 1, 23, 30, tzinfo=local))
    assert in_quiet_hours(night, datetime(2026, 1, 1, 6, 0, tzinfo=local))
    assert not in_quiet_hours(night, datetime(2026, 1, 1, 7, 0, tzinfo=local))
    n = Notifier(sender=lambda t, b: None, min_gap_s=0, quiet=lambda: True)
    assert n.maybe(state(status=Status.running), state(status=Status.error)) is False
