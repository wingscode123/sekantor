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
    # claude:a: 20 min for a reply and 5 min for approval, both answered (it ran on afterwards)
    assert st.waiting["waiting_input"] == timedelta(minutes=20)
    assert st.waiting["waiting_approval"] == timedelta(minutes=5)
    assert st.median("waiting_input") == timedelta(minutes=20) and len(st.answers["waiting_approval"]) == 1
    # claude:b still waits at the end of the window: not answered
    assert st.left_waiting == timedelta(minutes=30)
    assert st.longest_wait == timedelta(minutes=20) and st.longest_wait_session == "claude:a"
    assert st.sessions == 2 and st.by_host == {"orca": 1, "vscode": 1}


def test_a_wait_cut_short_by_the_session_ending_is_left_waiting(home):
    from ronda.hub.store import Store

    store = Store(home / "ronda.db")
    store.add_event(ev(20, "claude:c", "waiting_input", 60))
    store.add_event(Event(event_id="e21", ts=NOW - timedelta(minutes=50), source="claude-code", session_id="claude:c",
                          status="ended", type="session_ended"))
    store.close()
    st = compute(home, NOW - timedelta(hours=24), NOW)
    assert st.left_waiting == timedelta(minutes=30 + 10)  # claude:b's 30 + claude:c's 10


def test_window_clips_waits(home):
    st = compute(home, NOW - timedelta(minutes=110), NOW)
    assert st.waiting["waiting_input"] == timedelta(minutes=10)  # the answered wait, clipped to the window
    assert st.left_waiting == timedelta(minutes=30)


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


def test_an_unreachable_line_naming_the_event_counts_however_late_it_was_logged(home):
    # Under load a hook can log its timeout many seconds after the event's timestamp (seen: 7 s).
    late = ev(8, "claude:b", "running", 3)
    sent(home, [late])
    with open(home / "hook.log", "a", encoding="utf-8") as f:
        at = (late.ts + timedelta(seconds=20)).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        f.write(f"{at} SessionStart: hub unreachable (TimeoutError) e8\n")
    st = compute(home, NOW - timedelta(hours=24), NOW)
    assert [x.event_id for x in st.lost] == ["e6"]
    assert sorted(x.event_id for x in st.lost_hub_down) == ["e7", "e8"]
    assert st.hook_errors == {"hub unreachable": 2}
