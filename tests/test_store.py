from datetime import datetime, timedelta, timezone

from sekantor.hub.store import Store
from sekantor.schema import Event, Status

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


def test_subagent_report_expires_on_read_and_next_event(monkeypatch):
    st = Store(":memory:")
    ended = ev(2, None, type="subagent_ended", subagent={"id": "junior"})
    st.add_event(ended, received_at=ended.ts)
    st.add_event(ev(3, None, type="subagent_started", subagent={"id": "working"}), received_at=ended.ts)

    monkeypatch.setattr("sekantor.hub.store._now", lambda: ended.ts + timedelta(seconds=59))
    assert [a.id for a in st.session(ended.session_id).subagents] == ["working", "junior"]

    deadline = ended.ts + timedelta(seconds=60)
    monkeypatch.setattr("sekantor.hub.store._now", lambda: deadline)
    assert [a.id for a in st.session(ended.session_id).subagents] == ["working"]
    assert [a.id for a in st.sessions()[0].subagents] == ["working"]
    s = st.add_event(ev(4, Status.running, at=62), received_at=deadline)
    assert [a.id for a in s.subagents] == ["working"]
    st.close()


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


def test_a_new_database_has_no_actions_table(tmp_path):
    st = Store(tmp_path / "r.db")
    tables = {r[0] for r in st._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "actions" not in tables and {"events", "sessions"} <= tables


def test_an_old_database_with_an_actions_table_is_left_alone(tmp_path):
    import sqlite3

    db = sqlite3.connect(tmp_path / "r.db")
    db.execute("CREATE TABLE actions (id INTEGER PRIMARY KEY, session_id TEXT)")
    db.execute("INSERT INTO actions(session_id) VALUES ('claude:a')")
    db.commit()
    db.close()
    st = Store(tmp_path / "r.db")
    st.add_event(ev(1, Status.running))
    st.prune()
    assert st._db.execute("SELECT count(*) FROM actions").fetchone()[0] == 1
