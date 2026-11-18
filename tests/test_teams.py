from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from sekantor.hub.api import session_json, snapshot
from sekantor.hub.app import create_app
from sekantor.hub.status import apply
from sekantor.hub.store import Store
from sekantor.pos.claude_code.hook import build_event
from sekantor.schema import Event

NOW = datetime.now(timezone.utc)


def event(sid, *, at=0, source="claude-code", **fields):
    return Event(event_id=f"{sid}-{at}", session_id=sid, source=source, ts=NOW + timedelta(seconds=at), **fields)


def placement(identity, *, main=False, project="Office", creator=None, model=None):
    return event(
        f"orca-agent:{identity}", source="orca", type="orca_placement",
        orca={"session_id": identity, "project": project, "worktree": identity,
              "main": main, "creator": creator, "model": model},
    )


@pytest.mark.parametrize(("source", "host", "floor"), [
    ("claude-code", None, "claude"), ("claude-code", "terminal", "claude"),
    ("claude-code", "vscode", "claude"), ("claude-code", "claude-desktop", "claude"),
    ("claude-code", "orca", "orca"), ("orca", None, "orca"),
    ("claude-code", "openbot", "openbot"), ("openbot", "orca", "openbot"), ("orca", "openbot", "openbot"),
])
def test_floor_from_source_and_host(source, host, floor):
    s = apply(None, event("a", source=source, host={"app": host, "confidence": 1} if host else None))
    assert session_json(s)["floor"] == floor
    assert session_json(s)["team"] is None
    assert session_json(s)["report_to"] == "you"


def test_git_team_and_recent_lead_fallback(tmp_path):
    root = tmp_path / "Repo"
    (root / ".git").mkdir(parents=True)
    child = tmp_path / "feature"
    child.mkdir()
    (child / ".git").write_text("gitdir: ../Repo/.git/worktrees/other-name\n", encoding="utf-8")
    store = Store(":memory:")
    for sid, cwd, at in [("old", root, 0), ("recent", root, 1), ("junior", child, 2)]:
        store.add_event(event(sid, at=at, source="orca", workspace={"cwd": str(cwd)}, status="reported"))
    sessions = {s["session_id"]: s for s in snapshot(store)["sessions"]}
    assert sessions["recent"]["team"] == {
        "project": "Repo", "worktree": "Repo", "role": "lead", "lead": None, "model": None,
    }
    assert sessions["recent"]["report_pending"]
    assert sessions["junior"]["team"] == {
        "project": "Repo", "worktree": "feature", "role": "junior", "lead": "recent", "model": None,
    }
    assert sessions["junior"]["report_to"] == "lead"
    assert sessions["junior"]["report_pending"] is False
    store.close()


def test_placement_overrides_git_and_expires(tmp_path):
    (tmp_path / ".git").mkdir()
    store = Store(":memory:")
    p = placement("hook-agent")
    assert store.add_placement(p, NOW)
    assert not store.add_placement(p, NOW + timedelta(seconds=10))
    assert store.sessions() == []
    store.add_event(event("hook", source="orca", orca_session_id="hook-agent", workspace={"cwd": str(tmp_path)}))
    [s] = snapshot(store)["sessions"]
    assert (s["team"]["project"], s["team"]["role"]) == ("Office", "junior")
    assert "hook-agent" in store.placements(NOW + timedelta(seconds=119))
    assert store.placements(NOW + timedelta(seconds=120)) == {}
    assert store.expire_placements(NOW + timedelta(seconds=120))
    assert snapshot(store)["sessions"][0]["team"]["role"] == "lead"
    store.close()


def test_hook_identity_and_live_team_routing(tmp_path):
    token = "t" * 43
    headers = {"Authorization": f"Bearer {token}"}
    app = create_app(home=tmp_path, port=17879, token=token)
    with TestClient(app, base_url="http://127.0.0.1:17879", headers=headers) as client:
        def post(*events):
            response = client.post("/v1/events", json=[ev.model_dump(mode="json") for ev in events])
            assert response.status_code == 202, response.text
            assert response.json() == {"accepted": len(events), "duplicates": 0}

        env = {"ORCA_AGENT_SESSION_ID": "creator", "ORCA_TERMINAL_HANDLE": "structworker_creator"}
        hook = build_event({"session_id": "hook", "hook_event_name": "SessionStart"}, env)
        assert hook["orca_session_id"] == "creator"
        assert hook["orca_terminal_handle"] == "structworker_creator"
        post(Event.model_validate(hook),
             event("other", at=1, source="orca", orca=placement("recent", main=True).orca))
        worker = placement("worker", creator="creator", model="gpt-6.2-sol").orca
        post(event("orca:dispatch", source="orca", status="running", orca=worker, agent={"name": "codex"}))
        original_lead = app.state.store.session("claude:hook")
        assert original_lead.orca_terminal_handle == "structworker_creator"

        with client.websocket_connect("ws://127.0.0.1:17879/v1/stream", headers=headers) as ws:
            assert ws.receive_json()["type"] == "snapshot"
            post(placement("creator", main=True))
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert len(msg["sessions"]) == 3
            post(event("orca:dispatch", at=2, source="orca", status="reported", orca=worker))
            s = ws.receive_json()["session"]
            assert s["team"] == {
                "project": "Office", "worktree": "worker", "role": "junior",
                "lead": "claude:hook", "model": "gpt-6.2-sol",
            }
            assert s["report_to"] == "lead" and s["report_pending"] is False
            assert ws.receive_json()["type"] == "snapshot"

        [report] = client.get("/v1/sessions?status=reported").json()["sessions"]
        assert report["team"]["lead"] == "claude:hook"
        post(event("orca:dispatch", at=3, source="orca", status="waiting_approval", orca=worker))
        [approval] = client.get("/v1/sessions?status=waiting_approval").json()["sessions"]
        assert approval["needs_you"] and approval["report_to"] == "you"
        lead = app.state.store.session("claude:hook")
        assert lead == original_lead
