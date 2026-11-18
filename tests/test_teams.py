from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from sekantor import projects
from sekantor.hub.api import session_json, snapshot
from sekantor.hub.app import create_app
from sekantor.hub.status import apply, inbox_order
from sekantor.hub.store import Store
from sekantor.pos.claude_code.fingerprint import env_names
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
    if floor == "orca":
        with pytest.raises(ValueError, match="must have its team resolved"):
            session_json(s)
        store = Store(":memory:")
        s = store.add_event(event("a", source=source, host={"app": host, "confidence": 1} if host else None))
        store.close()
    assert session_json(s)["floor"] == floor
    assert session_json(s)["team"] is None
    assert session_json(s)["report_to"] == "you"


def test_git_team_and_recent_lead_fallback(tmp_path):
    root = tmp_path / "Repo"
    (root / ".git").mkdir(parents=True)
    child = tmp_path / "feature"
    child.mkdir()
    (child / ".git").write_text("gitdir: ../Repo/.git/worktrees/other-name\n", encoding="utf-8")
    (child / "subfolder").mkdir()
    store = Store(":memory:")
    for sid, cwd, at in [("old", root, 0), ("recent", root, 1), ("junior", child / "subfolder", -2)]:
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
    assert [s.session_id for s in inbox_order(store.sessions())] == ["old", "recent", "junior"]
    assert store.acknowledge_report("junior").acknowledged_at is None
    store.add_event(event("old", at=5, source="orca", status="ended"))
    store.add_event(event("recent", at=5, source="orca", status="ended"))
    assert store.session("junior").report_pending
    assert store.acknowledge_report("junior").acknowledged_at is not None
    store.close()


def test_placement_overrides_git_and_expires(tmp_path):
    (tmp_path / ".git").mkdir()
    store = Store(":memory:")
    p = placement("hook-agent")
    assert store.add_placement(p, NOW)
    assert not store.add_placement(p, NOW + timedelta(seconds=10))
    assert "hook-agent" in store.placements(NOW + timedelta(seconds=129))
    older = p.model_copy(update={"ts": NOW - timedelta(seconds=1), "orca": p.orca.model_copy(update={"main": True})})
    assert not store.add_placement(older, NOW + timedelta(seconds=20))
    assert store.sessions() == []
    store.add_event(event("hook", source="orca", orca_session_id="hook-agent", workspace={"cwd": str(tmp_path)}))
    [s] = snapshot(store)["sessions"]
    assert (s["team"]["project"], s["team"]["role"]) == ("Office", "junior")
    assert "hook-agent" in store.placements(NOW + timedelta(seconds=139))
    assert store.placements(NOW + timedelta(seconds=140)) == {}
    assert store.expire_placements(NOW + timedelta(seconds=140))
    assert snapshot(store)["sessions"][0]["team"]["role"] == "lead"
    store.close()


@pytest.mark.parametrize(("pointer", "expected"), [
    (r"C:\projects\Repo\.git\worktrees\internal", ("Repo", "checkout", False)),
    ("C:/projects/Repo/.git/worktrees/internal", ("Repo", "checkout", False)),
    ("../Repo/.git/modules/submodule", None),
])
def test_git_worktree_marker(tmp_path, pointer, expected):
    cwd = tmp_path / "checkout"
    cwd.mkdir()
    (cwd / ".git").write_text(f"gitdir: {pointer}\n", encoding="utf-8")
    assert projects.checkout(cwd) == expected


def test_creator_chain_and_project_alias(tmp_path):
    root = tmp_path / "Repo"
    (root / ".git").mkdir(parents=True)
    child = tmp_path / "feature"
    child.mkdir()
    (child / ".git").write_text("gitdir: ../Repo/.git/worktrees/feature\n", encoding="utf-8")
    store = Store(":memory:")
    store.add_event(event("original", source="orca", orca_session_id="root", workspace={"cwd": str(root)}))
    store.add_event(event("supervisor", source="orca", workspace={"cwd": str(child)},
                          orca=placement("supervisor", creator="root").orca))
    store.add_event(event("newer", at=3, source="orca", orca=placement("newer", main=True).orca))
    store.add_event(event("outsider", at=4, source="orca", orca=placement("outside", main=True, project="Elsewhere").orca))
    for creator, expected in [("supervisor", "original"), ("child-self", "newer"), ("outside", "newer")]:
        sid = creator if creator == "child-self" else f"child-{creator}"
        s = store.add_event(event(sid, source="orca", orca=placement(sid, creator=creator).orca))
        assert s.team.lead == expected
    store.add_event(event("newer", at=5, source="orca", status="ended"))
    assert store.session("child-self").team.lead == "original"
    store.close()


def test_custom_host_rules_keep_orca_identity(tmp_path, monkeypatch):
    from sekantor.hub.app import write_hook_env

    override = tmp_path / "custom.yaml"
    override.write_text("hosts: []\n", encoding="utf-8")
    monkeypatch.setenv("SEKANTOR_HOSTS", str(override))
    write_hook_env(tmp_path)
    expected = {"ORCA_AGENT_SESSION_ID", "ORCA_TERMINAL_HANDLE"}
    assert env_names({"hosts": []}) == expected
    assert expected <= set((tmp_path / "hook-env.txt").read_text().splitlines())


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
        response = client.post("/v1/hooks/claude", json={
            "v": 1, "id": "native", "ts": NOW.isoformat(), "env": env,
            "payload": {"session_id": "hook", "hook_event_name": "SessionStart"},
        })
        assert response.json()["stored"]
        post(event("other", at=1, source="orca", orca=placement("recent", main=True).orca))
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
            post(placement("creator", main=True))
            post(event("orca:dispatch", at=2, source="orca", status="reported", orca=worker))
            s = ws.receive_json()["session"]
            assert s["team"] == {
                "project": "Office", "worktree": "worker", "role": "junior",
                "lead": "claude:hook", "model": "gpt-6.2-sol",
            }
            assert s["report_to"] == "lead" and s["report_pending"] is False

        [report] = client.get("/v1/sessions?status=reported").json()["sessions"]
        assert report["team"]["lead"] == "claude:hook"
        post(event("orca:dispatch", at=3, source="orca", status="waiting_approval", orca=worker))
        [approval] = client.get("/v1/sessions?status=waiting_approval").json()["sessions"]
        assert approval["needs_you"] and approval["report_to"] == "you"
        lead = app.state.store.session("claude:hook")
        assert lead.model_dump() == original_lead.model_dump()
