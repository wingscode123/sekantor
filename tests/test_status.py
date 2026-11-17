"""Status engine: derives a session's state from its events (written before the engine)."""

from datetime import datetime, timedelta, timezone

import pytest

from sekantor.schema import Event, Status
from sekantor.hub.status import SessionState, apply, inbox_order, sweep, NEEDS_YOU

T0 = datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone.utc)


def ev(status, *, at=0, type="status_changed", sid="claude:s1", **kw) -> Event:
    return Event(
        event_id=f"e-{sid}-{at}-{status}-{type}",
        ts=T0 + timedelta(seconds=at),
        source="claude-code",
        session_id=sid,
        type=type,
        status=status,
        **kw,
    )


def run(*events) -> SessionState:
    state = None
    for e in events:
        state = apply(state, e)
    return state


# --- creating and moving through statuses ---------------------------------

def test_first_event_creates_session():
    s = run(ev(Status.waiting_input, type="session_started", workspace={"cwd": "/w", "branch": "main"}))
    assert s.session_id == "claude:s1"
    assert s.status is Status.waiting_input
    assert s.status_since == T0
    assert s.started_at == T0
    assert s.workspace.cwd == "/w" and s.workspace.branch == "main"


def test_running_then_waiting_then_ended():
    s = run(
        ev(Status.waiting_input, at=0, type="session_started"),
        ev(Status.running, at=5),
        ev(Status.waiting_input, at=30, summary="Done. Anything else?"),
        ev(Status.ended, at=90, type="session_ended"),
    )
    assert s.status is Status.ended
    assert s.status_since == T0 + timedelta(seconds=90)
    assert s.summary == "Done. Anything else?"
    assert s.ended_at == T0 + timedelta(seconds=90)


def test_same_status_keeps_status_since():
    s = run(ev(Status.running, at=0), ev(Status.running, at=20), ev(Status.running, at=40))
    assert s.status_since == T0
    assert s.last_event_at == T0 + timedelta(seconds=40)


def test_event_without_status_only_updates_details():
    s = run(ev(Status.running, at=0), ev(None, at=10, type="message", summary="Compacting"))
    assert s.status is Status.running
    assert s.status_since == T0
    assert s.summary == "Compacting"


def test_approval_keeps_request_until_status_changes():
    req = {"kind": "tool", "tool": "Bash", "input": "docker compose up -d"}
    s = run(ev(Status.running, at=0), ev(Status.waiting_approval, at=3, request=req))
    assert s.request.tool == "Bash"
    s = apply(s, ev(Status.running, at=9))
    assert s.request is None


# --- out of order delivery (hooks run async) -------------------------------

def test_older_event_does_not_override_newer_status():
    # PostToolUse (running, t=5) delivered after Stop (waiting_input, t=6)
    s = run(ev(Status.running, at=0), ev(Status.waiting_input, at=6), ev(Status.running, at=5))
    assert s.status is Status.waiting_input
    assert s.status_since == T0 + timedelta(seconds=6)
    assert s.last_event_at == T0 + timedelta(seconds=6)


# --- ended is terminal unless the session starts again ---------------------

def test_ended_ignores_later_status_events():
    s = run(ev(Status.running, at=0), ev(Status.ended, at=10, type="session_ended"), ev(Status.running, at=11))
    assert s.status is Status.ended


def test_resume_revives_ended_session():
    s = run(
        ev(Status.ended, at=10, type="session_ended"),
        ev(Status.waiting_input, at=20, type="session_started"),
    )
    assert s.status is Status.waiting_input
    assert s.ended_at is None


# --- host, pid, workspace merging -------------------------------------------

def test_keeps_most_confident_host():
    strong = {"app": "orca", "confidence": 0.99, "via": ["env_orca_session"]}
    weak = {"app": "terminal", "confidence": 0.5, "via": ["shell_parent"]}
    s = run(ev(Status.running, at=0, host=strong), ev(Status.running, at=1, host=weak))
    assert s.host.app == "orca"


def test_latest_pid_wins_and_missing_fields_do_not_erase():
    s = run(
        ev(Status.running, at=0, process={"pid": 100}, workspace={"cwd": "/w", "branch": "a"}),
        ev(Status.running, at=1, process={"pid": 200}, workspace={"cwd": "/w"}),
    )
    assert s.pid == 200
    assert s.workspace.branch == "a"


# --- inbox ordering (FR-10) --------------------------------------------------

def test_inbox_order_by_status_then_longest_wait():
    def mk(sid, status, since):
        return run(ev(status, at=since, sid=sid))

    sessions = [
        mk("claude:done", Status.done, 0),
        mk("claude:run", Status.running, 0),
        mk("claude:input-new", Status.waiting_input, 50),
        mk("claude:err", Status.error, 10),
        mk("claude:input-old", Status.waiting_input, 5),
        mk("claude:appr", Status.waiting_approval, 60),
        mk("claude:ended", Status.ended, 0),
    ]
    order = [s.session_id for s in inbox_order(sessions)]
    assert order == [
        "claude:appr",
        "claude:input-old",
        "claude:input-new",
        "claude:err",
        "claude:run",
        "claude:done",
        "claude:ended",
    ]


def test_needs_you_set():
    assert NEEDS_YOU == {Status.waiting_approval, Status.waiting_input, Status.error}


# --- FR-07: ended after 10 minutes of silence and the process gone ----------

@pytest.mark.parametrize(
    "silent_s, pid, alive, ended",
    [
        (601, 123, False, True),   # silent and dead
        (601, 123, True, False),   # silent but the process lives: still waiting for you
        (599, 123, False, False),  # not silent long enough
        (601, None, None, True),   # no pid reported: timeout alone (ADR-0006)
    ],
)
def test_sweep(silent_s, pid, alive, ended):
    s = run(ev(Status.waiting_input, at=0, process={"pid": pid} if pid else None))
    now = T0 + timedelta(seconds=silent_s)
    out = sweep(s, now, pid_alive=lambda p: alive)
    if ended:
        assert out is not None and out.status is Status.ended and out.status_since == now
    else:
        assert out is None


def test_sweep_leaves_ended_alone():
    s = run(ev(Status.ended, at=0, type="session_ended"))
    assert sweep(s, T0 + timedelta(hours=1), pid_alive=lambda p: False) is None


# --- M2: pending requests carry an id (ADR-0008) ------------------------------

def test_reply_request_kept_while_waiting_for_input():
    s = run(ev(Status.running, at=0), ev(Status.waiting_input, at=5, request={"kind": "input", "id": "stop-1"}))
    assert s.request.kind == "input" and s.request.id == "stop-1"
    s = apply(s, ev(Status.waiting_input, at=60, type="message"))  # idle_prompt: same wait, same request
    assert s.request.id == "stop-1"
    s = apply(s, ev(Status.running, at=70))
    assert s.request is None


def test_new_approval_replaces_request():
    s = run(
        ev(Status.waiting_approval, at=0, request={"kind": "tool", "tool": "Bash", "input": "ls", "id": "p1"}),
        ev(Status.running, at=2),
        ev(Status.waiting_approval, at=4, request={"kind": "tool", "tool": "Bash", "input": "rm x", "id": "p2"}),
    )
    assert s.request.id == "p2"


def test_permission_prompt_notification_keeps_request():
    s = run(
        ev(Status.waiting_approval, at=0, request={"kind": "tool", "tool": "Bash", "input": "ls", "id": "p1"}),
        ev(Status.waiting_approval, at=6),
    )
    assert s.request.id == "p1"


# --- capabilities belong to the pending request ---------------------------------

def _ask(at, rid, caps, cmd="npm test"):
    return ev(Status.waiting_approval, at=at, capabilities=caps,
              request={"kind": "tool", "tool": "Bash", "input": cmd, "id": rid})


def test_capabilities_follow_the_request():
    s = run(ev(Status.waiting_input, at=0, capabilities=["reply"], request={"kind": "input", "id": "s1"}),
            ev(Status.running, at=5))
    assert s.capabilities == []
    s = apply(s, _ask(6, "p1", ["approve", "deny"]))
    assert s.capabilities == ["approve", "deny"]


def test_a_different_question_replaces_even_without_capabilities():
    s = run(_ask(0, "p1", ["approve", "deny"]), _ask(1, "p2", [], cmd="rm x"))
    assert s.request.id == "p2" and s.capabilities == []


def test_events_well_after_end_revive_a_session_whose_restart_was_missed():
    # Orca/desktop restart the CLI: SessionEnd, then SessionStart(resume). If the hub missed the
    # SessionStart, later events from the live process must still bring the session back.
    s = run(ev(Status.running, at=0), ev(Status.ended, at=10, type="session_ended"), ev(Status.running, at=40))
    assert s.status is Status.running and s.ended_at is None


# --- activity -------------------------------------------------------------

def test_activity_is_kept_while_running_and_cleared_when_status_changes():
    s = run(ev(Status.running, at=0, activity={"tool": "Read", "kind": "read"}))
    assert s.activity == {"tool": "Read", "kind": "read"}
    s = apply(s, ev(Status.running, at=1))  # PostToolUse: running, no activity
    assert s.activity == {"tool": "Read", "kind": "read"}
    s = apply(s, ev(Status.running, at=2, activity={"tool": "Bash", "kind": "run"}))
    assert s.activity == {"tool": "Bash", "kind": "run"}
    s = apply(s, ev(Status.done, at=3))
    assert s.activity is None


def test_activity_cleared_when_waiting():
    s = run(ev(Status.running, at=0, activity={"tool": "Edit", "kind": "edit"}), ev(Status.waiting_input, at=1))
    assert s.activity is None
