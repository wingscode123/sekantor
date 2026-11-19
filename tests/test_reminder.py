"""A4: one reminder per waiting episode, from the sweep, through the Notifier."""

import asyncio
import time
from datetime import datetime, timedelta, timezone

from sekantor import config
from sekantor.hub.app import sweep_tick
from sekantor.hub.notify import Notifier
from sekantor.hub.status import SessionState
from sekantor.hub.store import Store
from sekantor.hub.stream import Broadcaster
from sekantor.schema import Event, Request, Status, Workspace

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def waiting(sid="claude:a", minutes=11, status=Status.waiting_approval, **kw):
    since = NOW - timedelta(minutes=minutes)
    return SessionState(session_id=sid, source="claude-code", status=status, status_since=since, status_ts=since,
                        started_at=since, last_event_at=since, workspace=Workspace(cwd="/work/demo"), **kw)


def notifier(sent, **kw):
    return Notifier(sender=lambda t, b: sent.append((t, b)), min_gap_s=0, **kw)


def wait_for(sent, n):
    end = time.time() + 2
    while len(sent) < n and time.time() < end:
        time.sleep(0.01)


def test_setting_defaults_and_loads(tmp_path):
    assert config.Settings().remind_after_minutes == 10
    (tmp_path / "config.toml").write_text("remind_after_minutes = 5\n")
    assert config.settings(tmp_path).remind_after_minutes == 5
    (tmp_path / "config.toml").write_text("remind_after_minutes = 0\n")
    assert config.settings(tmp_path).remind_after_minutes == 0
    (tmp_path / "config.toml").write_text('remind_after_minutes = "soon"\n')
    s, problems = config.load(tmp_path)
    assert s.remind_after_minutes == 10 and len(problems) == 1
    (tmp_path / "config.toml").write_text("remind_after_minutes = -3\n")
    assert len(config.load(tmp_path)[1]) == 1


def test_reminds_once_after_the_threshold():
    sent = []
    n = notifier(sent)
    s = waiting(minutes=11)
    assert n.remind([s], NOW, 10) == 1
    assert n.remind([s], NOW + timedelta(minutes=5), 10) == 0
    wait_for(sent, 1)
    assert len(sent) == 1 and "11m" in sent[0][1]


def test_not_before_the_threshold_and_off_at_zero():
    sent = []
    n = notifier(sent)
    assert n.remind([waiting(minutes=9)], NOW, 10) == 0
    assert n.remind([waiting(minutes=60)], NOW, 0) == 0
    assert n.remind([waiting(minutes=10)], NOW, 10) == 1


def test_snooze_and_non_waiting_states_are_skipped():
    sent = []
    n = notifier(sent)
    snoozed = waiting(snoozed_until=NOW + timedelta(hours=1))
    assert n.remind([snoozed], NOW, 10) == 0
    assert n.remind([waiting(status=Status.running), waiting(status=Status.ended)], NOW, 10) == 0
    idle = waiting(status=Status.waiting_input)  # no question: nothing for you to do
    assert n.remind([idle], NOW, 10) == 0
    reported_to_lead = waiting(status=Status.reported, reported_to_lead_at=NOW)
    assert n.remind([reported_to_lead], NOW, 10) == 0
    snoozed.snoozed_until = NOW - timedelta(minutes=1)  # expired: now it reminds
    assert n.remind([snoozed], NOW, 10) == 1


def test_a_new_status_starts_a_new_episode():
    sent = []
    n = notifier(sent)
    assert n.remind([waiting(minutes=11)], NOW, 10) == 1
    again = waiting(minutes=12, status=Status.waiting_input, request=Request(kind="question"))
    assert n.remind([again], NOW, 10) == 1


def test_disabled_or_quiet_notifier_sends_nothing():
    sent = []
    assert notifier(sent, enabled=False).remind([waiting()], NOW, 10) == 0
    quiet = notifier(sent, quiet=lambda: True)
    assert quiet.remind([waiting()], NOW, 10) == 0
    quiet.quiet = lambda: False  # quiet hours over: the reminder was not used up
    assert quiet.remind([waiting()], NOW, 10) == 1


def test_sweep_tick_reminds(tmp_path):
    sent = []
    store = Store(tmp_path / "sekantor.db")
    ts = datetime.now(timezone.utc) - timedelta(minutes=6)  # under the 10 min silence limit
    store.add_event(Event(event_id="e1", ts=ts, source="claude-code", session_id="claude:a",
                          status=Status.waiting_approval, process={"pid": 1}))
    n = notifier(sent)
    settings = config.Settings(remind_after_minutes=5)

    async def main():
        await sweep_tick(store, Broadcaster(), settings, n)
        await sweep_tick(store, Broadcaster(), settings, n)

    asyncio.run(main())
    wait_for(sent, 1)
    assert len(sent) == 1
    store.close()
