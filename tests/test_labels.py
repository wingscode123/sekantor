"""The inbox and desktop toasts name agents and hosts the same way."""

from datetime import datetime, timezone

from ronda.hub.api import session_json
from ronda.hub.notify import message
from ronda.hub.status import SessionState
from ronda.schema import Host, Status, Workspace


def state(source: str, app: str | None) -> SessionState:
    now = datetime.now(timezone.utc)
    return SessionState(session_id="s1", source=source, status=Status.waiting_approval, status_since=now,
                        status_ts=now, started_at=now, last_event_at=now, workspace=Workspace(cwd="/w/shop"),
                        host=Host(app=app, confidence=0.9, via=["x"]) if app else None)


def test_every_channel_uses_the_same_names():
    s = state("codex", "jetbrains")
    j = session_json(s)
    assert (j["source_label"], j["host_label"]) == ("Codex", "JetBrains")
    assert message(s) == ("Approval needed", "Codex in JetBrains, shop")


def test_unknown_ids_show_as_is():
    j = session_json(state("my-agent", None))
    assert (j["source_label"], j["host_label"]) == ("my-agent", None)
    assert message(state("my-agent", "my-app"))[1] == "my-agent in my-app, shop"
