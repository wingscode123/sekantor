"""The daily standup ("Rapat"): what the agents did in a time window, deterministic and from the store only.

One windowed read over the events table (the ``events_ts`` index) pulls just the three JSON fields the digest
needs, so a day of data costs tens of milliseconds. Waits reuse ``sekantor stats`` so both commands agree:
only approvals and questions count (ADR-0027), clipped to the window, and an open wait counts up to ``until``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sekantor import projects
from sekantor.config import Settings
from sekantor.hub.status import SessionState
from sekantor.schema import Status
from sekantor.stats import Stats, _waiting, parse_since

SUMMARY_MAX = 240

# Answered from the events_digest covering index alone. Rows come back by time; a session's own events keep
# their insertion order because the index ends in the row id.
_WINDOW_SQL = (
    "SELECT session_id, ts, status, req_kind, act_kind FROM events WHERE ts >= ? AND ts <= ? ORDER BY ts, session_id"
)
# The last status a session reported before the window: the state its first in-window wait starts from.
_BEFORE_SQL = (
    "SELECT ts, status, req_kind FROM events WHERE session_id = ? AND ts < ? AND status IS NOT NULL "
    "ORDER BY ts DESC, seq DESC LIMIT 1"
)


def parse_range(text: str, now: datetime | None = None) -> datetime:
    """``today`` (local midnight), ``8h`` / ``90m`` / ``2d`` back from now, or an ISO 8601 time (naive = local)."""
    now = (now or datetime.now(timezone.utc)).astimezone()
    text = text.strip()
    if text.lower() == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return now - parse_since(text)
    except ValueError:
        pass
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("use today, a number and m, h or d (8h), or a time like 2026-11-19T08:00") from None
    return when if when.tzinfo else when.astimezone()


def _project(s: SessionState, settings: Settings | None) -> dict | None:
    if s.floor == "openbot":
        return {"name": "OpenBot agents", "kind": "other"}
    if not (s.workspace and s.workspace.cwd):
        return None
    project = projects.detect(s.workspace.cwd)
    if settings and (override := settings.projects.get(project["name"])):
        project["kind"] = override
    return {"name": project["name"], "kind": project["kind"]}


def _waiting_now(s: SessionState) -> bool:
    """An approval or a question: the waits ``sekantor stats`` counts."""
    return s.status is Status.waiting_approval or (
        s.status is Status.waiting_input and s.request is not None and s.request.kind == "question")


def compute(store, since: datetime, until: datetime, settings: Settings | None = None) -> dict:
    since, until = since.astimezone(timezone.utc), until.astimezone(timezone.utc)
    states = {s.session_id: s for s in store.sessions()}
    rows = store.query(_WINDOW_SQL, (since.isoformat(), until.isoformat()))

    first: dict[str, str] = {}
    last: dict[str, str] = {}
    tools: dict[str, Counter] = defaultdict(Counter)
    turns: Counter = Counter()
    errors: Counter = Counter()
    status_rows: dict[str, list[tuple]] = defaultdict(list)
    prev: dict[str, object] = {}
    for sid, ts, status, request_kind, activity_kind in rows:
        first.setdefault(sid, ts)
        last[sid] = ts
        if activity_kind:
            tools[sid][activity_kind] += 1
        if status:
            # Repeats of one status (a run of tool events) add nothing to the waits: keep the changes only.
            mapped = (status, request_kind) if status == "waiting_input" else status
            if mapped != prev.get(sid):
                prev[sid] = mapped
                status_rows[sid].append((sid, ts, status, None, request_kind))
            if status == "reported":
                turns[sid] += 1
            elif status == "error":
                errors[sid] += 1

    # Sessions waiting on you right now belong in the standup even if they went quiet before the window.
    sids = set(first) | {sid for sid, s in states.items() if _waiting_now(s)}
    wait_rows: list[tuple] = []
    for sid in sorted(sids):
        before = store.query(_BEFORE_SQL, (sid, since.isoformat()))
        if before:
            ts, status, request_kind = before[0]
            wait_rows.append((sid, ts, status, None, request_kind))
        wait_rows += status_rows.get(sid, [])
    st = Stats(since=since, until=until)
    ended = {sid: s.ended_at for sid, s in states.items() if s.status is Status.ended and s.ended_at}
    _waiting(st, wait_rows, ended)

    asked: Counter = Counter()
    waited: dict[str, timedelta] = defaultdict(timedelta)
    longest = timedelta()
    for sid, _, a, b, _ in st.waits:
        asked[sid] += 1
        waited[sid] += b - a
        longest = max(longest, b - a)

    now = datetime.now(timezone.utc)
    out = []
    for sid in sids:
        s = states.get(sid)
        out.append({
            "session_id": sid,
            "agent": s.agent.name if s and s.agent else None,
            "model": s.agent.model if s and s.agent else None,
            "project": _project(s, settings) if s else None,
            "floor": s.floor if s else "claude",
            "branch": s.workspace.branch if s and s.workspace else None,
            "first_at": first.get(sid),
            "last_at": last.get(sid),
            "turns": turns[sid],
            "tools": dict(tools[sid]),
            "asked": asked[sid],
            "wait_s": int(waited[sid].total_seconds()),
            "errors": errors[sid],
            "summary": (s.summary or "")[:SUMMARY_MAX] if s else "",
            "status": s.status.value if s else "ended",
            "status_since": s.status_since.isoformat() if s else None,
            "waiting": bool(s and _waiting_now(s)),
            "needs_you": bool(s and s.needs_you),
        })
    out.sort(key=lambda r: (
        not r["waiting"], not r["needs_you"],
        r["status_since"] or "" if r["needs_you"] else "",
        (r["project"] or {}).get("name") or "~", r["floor"], r["agent"] or "", r["session_id"],
    ))
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "generated_at": now.isoformat(),
        "totals": {
            "agents": len(out),
            "turns": sum(r["turns"] for r in out),
            "asked": sum(r["asked"] for r in out),
            "wait_s": sum(r["wait_s"] for r in out),
            "longest_wait_s": int(longest.total_seconds()),
            "errors": sum(r["errors"] for r in out),
            "waiting_now": sum(r["waiting"] for r in out),
        },
        "sessions": out,
    }
