from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from ronda.cli import app
from ronda.hub.store import Store
from ronda.schema import Event
from ronda.stats import compute, parse_since

NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)


def ev(i, sid, status, at_min, host=None):
    return Event(event_id=f"e{i}", ts=NOW - timedelta(minutes=at_min), source="claude-code", session_id=sid,
                 status=status, host={"app": host, "confidence": 0.9} if host else None)


def sent(home, events):
    with open(home / "sent.log", "a", encoding="utf-8") as f:
        for e in events:
            f.write(f"{e.ts.isoformat()} {e.event_id} {e.session_id} {e.status.value}\n")


@pytest.fixture
def home(tmp_path):
    store = Store(tmp_path / "ronda.db")
    stored = [
        ev(1, "claude:a", "waiting_input", 120, host="orca"),
        ev(2, "claude:a", "running", 100),       # waited 20 min for a reply
        ev(3, "claude:a", "waiting_approval", 90),
        ev(4, "claude:a", "running", 85),        # waited 5 min for approval
        ev(5, "claude:b", "waiting_input", 30, host="vscode"),  # still waiting: 30 min to now
    ]
    for e in stored:
        store.add_event(e)
    store.close()
    lost = ev(6, "claude:b", "running", 10)          # hub up, nothing logged: a real loss
    dropped = ev(7, "claude:b", "running", 5)        # hub down: the hook logged it
    sent(tmp_path, stored + [lost, dropped])
    (tmp_path / "hook.log").write_text(
        (NOW - timedelta(minutes=5)).astimezone().strftime("%Y-%m-%dT%H:%M:%S") + " PreToolUse: hub unreachable (TimeoutError)\n"
    )
    return tmp_path


def test_lost_events_are_attempts_the_hub_never_stored(home):
    st = compute(home, NOW - timedelta(hours=24), NOW)
    assert st.attempted == 7 and st.stored == 5
    assert [x.event_id for x in st.lost] == ["e6"]
    assert [x.event_id for x in st.lost_hub_down] == ["e7"]
    assert st.hook_errors == {"hub unreachable": 1}


def test_waiting_time_and_sessions(home):
    st = compute(home, NOW - timedelta(hours=24), NOW)
    assert st.waiting["waiting_input"] == timedelta(minutes=50)
    assert st.waiting["waiting_approval"] == timedelta(minutes=5)
    assert st.longest_wait == timedelta(minutes=30) and st.longest_wait_session == "claude:b"
    assert st.sessions == 2 and st.by_host == {"orca": 1, "vscode": 1}


def test_window_clips_waits(home):
    st = compute(home, NOW - timedelta(minutes=110), NOW)
    assert st.waiting["waiting_input"] == timedelta(minutes=40)  # 10 of the first 20 + 30


def test_recent_attempts_are_in_flight(home):
    st = compute(home, NOW - timedelta(hours=24), NOW - timedelta(minutes=10) + timedelta(seconds=5))
    assert st.lost == [] and st.lost_hub_down == []


def test_parse_since():
    assert parse_since("90m") == timedelta(minutes=90)
    assert parse_since("7d") == timedelta(days=7)
    with pytest.raises(ValueError):
        parse_since("soon")


def test_cli_stats_clean_home(tmp_path, monkeypatch):
    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    r = CliRunner().invoke(app, ["stats"])
    assert r.exit_code == 0 and "lost 0" in r.output


def test_hook_records_what_it_sends(tmp_path, monkeypatch):
    from ronda.pos.claude_code import hook

    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    hook._record_sent({"ts": "2026-11-12T18:00:00+00:00", "event_id": "x1", "session_id": "claude:z", "status": "running"})
    assert (tmp_path / "sent.log").read_text() == "2026-11-12T18:00:00+00:00 x1 claude:z running\n"
