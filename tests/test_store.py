from datetime import datetime, timedelta, timezone

from ronda.hub.store import Store
from ronda.schema import Event, Status

T0 = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)


def ev(i, status, sid="claude:a", at=None, **kw):
    return Event(event_id=f"e{i}", ts=T0 + timedelta(seconds=at if at is not None else i), source="claude-code",
                 session_id=sid, status=status, **kw)


def test_add_event_updates_session(tmp_path):
    st = Store(tmp_path / "r.db")
    s = st.add_event(ev(1, Status.running))
    assert s.status is Status.running
    s = st.add_event(ev(2, Status.waiting_input, summary="ok?"))
    assert st.session("claude:a").status is Status.waiting_input
    assert st.session("claude:a").summary == "ok?"


def test_duplicate_event_is_ignored(tmp_path):
    st = Store(tmp_path / "r.db")
    assert st.add_event(ev(1, Status.running)) is not None
    assert st.add_event(ev(1, Status.running)) is None
    assert len(st.events("claude:a")) == 1


def test_persists_across_reopen(tmp_path):
    p = tmp_path / "r.db"
    st = Store(p)
    st.add_event(ev(1, Status.waiting_approval, request={"tool": "Bash", "input": "ls"}))
    st.close()
    st2 = Store(p)
    s = st2.session("claude:a")
    assert s.status is Status.waiting_approval and s.request.input == "ls"


def test_sessions_filter_and_events_order(tmp_path):
    st = Store(tmp_path / "r.db")
    st.add_event(ev(1, Status.running, sid="claude:a"))
    st.add_event(ev(2, Status.waiting_input, sid="claude:b"))
    st.add_event(ev(3, Status.running, sid="claude:a", at=0))  # arrives late, older ts
    assert {s.session_id for s in st.sessions(Status.running)} == {"claude:a"}
    assert len(st.sessions()) == 2
    assert [e.event_id for e in st.events("claude:a")] == ["e3", "e1"]


def test_events_limit_returns_latest(tmp_path):
    st = Store(tmp_path / "r.db")
    for i in range(60):
        st.add_event(ev(i, Status.running))
    evs = st.events("claude:a", limit=50)
    assert len(evs) == 50 and evs[0].event_id == "e10" and evs[-1].event_id == "e59"


def test_prune_retention(tmp_path):
    st = Store(tmp_path / "r.db")
    st.add_event(ev(1, Status.ended, type="session_ended"), received_at=T0)
    st.add_event(ev(2, Status.running, sid="claude:b"), received_at=T0 + timedelta(days=6))
    assert st.prune(now=T0 + timedelta(days=8)) == 1
    assert st.events("claude:a") == []
    assert len(st.events("claude:b")) == 1


# --- actions / audit (ADR-0010) -------------------------------------------------

def test_action_lifecycle(tmp_path):
    st = Store(tmp_path / "r.db")
    a = st.add_action("claude:a", "approve", "p1", None, "web", "me")
    assert a["outcome"] == "pending" and a["channel"] == "web"
    assert st.take_action("claude:a", "p2", ("approve", "deny")) is None  # other request
    got = st.take_action("claude:a", "p1", ("approve", "deny"))
    assert got["id"] == a["id"] and got["outcome"] == "delivered"
    assert st.take_action("claude:a", "p1", ("approve", "deny")) is None  # delivered once


def test_newer_answer_supersedes_and_stale_expire(tmp_path):
    st = Store(tmp_path / "r.db")
    first = st.add_action("claude:a", "approve", "p1", None, "web", "me")
    st.add_action("claude:a", "deny", "p1", None, "cli", "me")
    st.add_action("claude:a", "reply", "s1", "hi", "web", "me")
    assert st.expire_actions("claude:a", keep_request_id="p1") == 1  # the reply to s1
    outcomes = {x["id"]: x["outcome"] for x in st.actions("claude:a")}
    assert outcomes[first["id"]] == "superseded"
    assert st.take_action("claude:a", "p1", ("approve", "deny"))["type"] == "deny"
    assert [x["type"] for x in st.actions()] == ["reply", "deny", "approve"]
