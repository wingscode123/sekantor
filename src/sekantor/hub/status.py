"""Status engine: a session's current state is a fold over its events.

Pure functions, no I/O: ``apply`` (one event), ``inbox_order`` (FR-10), ``sweep`` (FR-07).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Literal

from pydantic import BaseModel

from sekantor.schema import SUBAGENT_EVENTS, Activity, Agent, Capability, Event, Host, Request, Status, Workspace

NEEDS_YOU = {Status.waiting_approval, Status.waiting_input, Status.error}
WAITING = {Status.waiting_approval, Status.waiting_input}

# FR-10: waiting_approval > waiting_input > error > running > reported > done (ended last, as history).
PRIORITY = {
    Status.waiting_approval: 0,
    Status.waiting_input: 1,
    Status.error: 2,
    Status.running: 3,
    Status.reported: 4,
    Status.done: 5,
    Status.ended: 6,
}

SILENCE_TIMEOUT = timedelta(minutes=10)
ENDED_GRACE = timedelta(seconds=15)
SUBAGENT_REPORT_TTL = timedelta(seconds=60)


class SubagentState(BaseModel):
    id: str
    type: str = "unknown"
    status: Literal["working", "reported"] = "working"
    activity: Activity | None = None
    summary: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class SessionState(BaseModel):
    session_id: str
    source: str
    status: Status
    status_since: datetime
    status_ts: datetime  # ts of the event that set the current status (for out-of-order events)
    started_at: datetime
    last_event_at: datetime
    ended_at: datetime | None = None
    acknowledged_at: datetime | None = None
    agent: Agent | None = None
    workspace: Workspace = Workspace()
    host: Host | None = None
    summary: str | None = None
    request: Request | None = None
    capabilities: list[Capability] = []
    pid: int | None = None
    activity: dict | None = None  # {"tool", "kind"} of the last tool started while running (ADR-0022)
    subagents: list[SubagentState] = []
    snoozed_until: datetime | None = None  # FR-15: no notifications until then

    def prune_subagents(self, now: datetime) -> None:
        cutoff = now - SUBAGENT_REPORT_TTL
        self.subagents = [a for a in self.subagents if a.ended_at is None or a.ended_at > cutoff]

    def snoozed(self, now: datetime) -> bool:
        return self.snoozed_until is not None and self.snoozed_until > now

    @property
    def needs_you(self) -> bool:
        if self.status is Status.waiting_input:
            return self.request is not None and self.request.kind == "question"
        return self.status in NEEDS_YOU

    @property
    def report_pending(self) -> bool:
        return self.status is Status.reported and (
            self.acknowledged_at is None or self.acknowledged_at < self.status_since
        )


def _merge_workspace(old: Workspace, new: Workspace | None) -> Workspace:
    if new is None:
        return old
    return Workspace(cwd=new.cwd or old.cwd, branch=new.branch or old.branch)


def _activity(event: Event) -> dict | None:
    return event.activity.model_dump() if event.activity else None


def _apply_subagent(state: SessionState | None, event: Event) -> SessionState:
    # A child can arrive before SessionStart. Allow an earlier parent event to replace the default status.
    s = state.model_copy(deep=True) if state else SessionState(
        session_id=event.session_id,
        source=event.source,
        status=Status.running,
        status_since=event.ts,
        status_ts=datetime.min.replace(tzinfo=timezone.utc),
        started_at=event.ts,
        last_event_at=event.ts,
        agent=event.agent,
        workspace=_merge_workspace(Workspace(), event.workspace),
        host=event.host,
        pid=event.process.pid if event.process else None,
    )
    s.last_event_at = max(s.last_event_at, event.ts)
    if event.subagent is None or event.type not in SUBAGENT_EVENTS:
        return s
    worker = next((a for a in s.subagents if a.id == event.subagent.id), None)
    if worker is None:
        worker = SubagentState(id=event.subagent.id, started_at=event.ts)
        s.subagents.append(worker)
    worker.started_at = min(worker.started_at, event.ts)
    if event.subagent.type:
        worker.type = event.subagent.type
    if event.type == "subagent_ended" and (worker.ended_at is None or event.ts >= worker.ended_at):
        worker.status = "reported"
        worker.summary = event.summary
        worker.ended_at = event.ts
        worker.activity = None
    elif event.type == "subagent_activity" and worker.status == "working":
        worker.activity = event.activity
    s.subagents.sort(key=lambda a: a.status == "reported")
    return s


def apply(state: SessionState | None, event: Event) -> SessionState:
    """Return the session state after ``event``. Never mutates ``state``."""
    if event.type in SUBAGENT_EVENTS or event.subagent is not None:
        return _apply_subagent(state, event)
    if state is None:
        status = event.status or Status.running
        return SessionState(
            session_id=event.session_id,
            source=event.source,
            status=status,
            status_since=event.ts,
            status_ts=event.ts,
            started_at=event.ts,
            last_event_at=event.ts,
            ended_at=event.ts if status is Status.ended else None,
            agent=event.agent,
            workspace=_merge_workspace(Workspace(), event.workspace),
            host=event.host,
            summary=event.summary,
            request=event.request if status in WAITING or status is Status.reported else None,
            capabilities=list(event.capabilities),
            pid=event.process.pid if event.process else None,
            activity=_activity(event) if status is Status.running else None,
        )

    s = state.model_copy(deep=True)
    newer = event.ts >= s.status_ts
    s.last_event_at = max(s.last_event_at, event.ts)
    if event.type == "session_started":
        s.started_at = min(s.started_at, event.ts)

    # Details that are safe to take from any event, in any order.
    if event.agent is not None:
        s.agent = Agent(name=event.agent.name, model=event.agent.model or (s.agent.model if s.agent else None))
    s.workspace = _merge_workspace(s.workspace, event.workspace)
    if event.host is not None and (s.host is None or event.host.confidence >= s.host.confidence):
        s.host = event.host
    if event.process is not None and newer:
        s.pid = event.process.pid

    if not newer:
        return s  # stale for status purposes: keep it in the timeline only

    if (event.source == "claude-code" and event.type == "message" and event.status is None
            and event.request is not None and event.request.kind == "report"):
        # Claude's idle prompt is a fallback when the Stop event was missed.
        if s.status is not Status.running:
            return s
        event = event.model_copy(update={"status": Status.reported, "summary": s.summary})

    if event.summary:
        s.summary = event.summary

    # `ended` is terminal; a new session_started (resume) revives it, and so does a status event well
    # after the end (the restart's SessionStart was missed, e.g. while the hub was down). Events within
    # the grace period are stragglers from before the end (async hooks).
    if s.status is Status.ended and event.type != "session_started":
        revived = event.status is not None and s.ended_at is not None and event.ts - s.ended_at > ENDED_GRACE
        if not revived:
            return s

    if (event.status is Status.waiting_approval and event.request is None and s.status is Status.waiting_input
            and s.request is not None and s.request.kind == "question"):
        return s  # the permission notification that follows a question (AskUserQuestion)

    if event.status is not None:
        changed = event.status is not s.status
        if changed or event.status is Status.reported:
            s.status = event.status
            s.status_since = event.ts
        if s.status is Status.reported:
            s.acknowledged_at = None
            s.summary = event.summary
        s.status_ts = event.ts
        if s.status is Status.running:
            s.activity = _activity(event) or s.activity
        else:
            s.activity = None
        if s.status is Status.ended:
            s.ended_at = event.ts
        else:
            s.ended_at = None
        if s.status in WAITING:
            if event.request is None:
                # A repeat of the same wait (the idle or permission notification) keeps the request.
                if changed:
                    s.request, s.capabilities = None, list(event.capabilities)
            else:
                s.request, s.capabilities = event.request, list(event.capabilities)
        else:
            s.request = event.request if s.status is Status.reported else None
            s.capabilities = list(event.capabilities)
    return s


def sort_key(s: SessionState) -> tuple:
    """Status priority first, then the longest wait (oldest status_since) first."""
    return (PRIORITY[s.status], s.status_since)


def inbox_order(sessions: Iterable[SessionState]) -> list[SessionState]:
    return sorted(sessions, key=sort_key)


def sweep(
    s: SessionState,
    now: datetime,
    pid_alive: Callable[[int], bool],
    timeout: timedelta = SILENCE_TIMEOUT,
) -> SessionState | None:
    """FR-07: return the session marked ``ended`` if it should be, else None."""
    if s.status is Status.ended or now - s.last_event_at <= timeout:
        return None
    if s.pid is not None and pid_alive(s.pid):
        return None
    out = s.model_copy(deep=True)
    out.status = Status.ended
    out.status_since = now
    out.status_ts = now
    out.ended_at = now
    out.request = None
    return out
