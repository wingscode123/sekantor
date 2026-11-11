from datetime import timezone

import pytest
from pydantic import ValidationError

from ronda.schema import Event, Status

PRD_EXAMPLE = {
    "v": 1,
    "event_id": "01JC0000000000000000000000",
    "ts": "2026-11-10T10:21:04Z",
    "source": "claude-code",
    "session_id": "claude:7f3a",
    "agent": {"name": "claude", "model": "opus"},
    "workspace": {"cwd": "/home/u/aipy", "branch": "feat/ocr"},
    "host": {"app": "orca", "confidence": 0.9, "via": ["process_tree", "cwd"]},
    "type": "status_changed",
    "status": "waiting_approval",
    "summary": "Wants to run: docker compose up -d",
    "request": {"kind": "tool", "tool": "Bash", "input": "docker compose up -d"},
    "capabilities": ["approve", "deny", "reply", "open"],
}


def test_prd_example_is_valid():
    e = Event.model_validate(PRD_EXAMPLE)
    assert e.status is Status.waiting_approval
    assert e.host.app == "orca"
    assert e.process is None
    assert e.ts.tzinfo is timezone.utc


def test_process_pid_optional_field():
    e = Event.model_validate({**PRD_EXAMPLE, "process": {"pid": 4242}})
    assert e.process.pid == 4242


def test_unknown_fields_are_ignored():
    e = Event.model_validate({**PRD_EXAMPLE, "future_field": {"x": 1}})
    assert not hasattr(e, "future_field")


def test_naive_timestamp_is_utc():
    e = Event.model_validate({**PRD_EXAMPLE, "ts": "2026-11-10T10:21:04"})
    assert e.ts.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "patch",
    [
        {"v": 2},
        {"status": "sleeping"},
        {"type": "whatever"},
        {"capabilities": ["format_disk"]},
        {"host": {"app": "orca", "confidence": 1.5}},
        {"event_id": ""},
        {"process": {"pid": 0}},
    ],
)
def test_invalid_events_rejected(patch):
    with pytest.raises(ValidationError):
        Event.model_validate({**PRD_EXAMPLE, **patch})


def test_status_values_match_adr_0002():
    assert [s.value for s in Status] == [
        "waiting_approval", "waiting_input", "error", "running", "done", "ended",
    ]
