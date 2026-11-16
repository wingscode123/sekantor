"""HTTP API v1 (PRD "API hub")."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from ronda import __version__, labels
from ronda.hub.status import SessionState, inbox_order
from ronda.hub.store import SLOW_S
from ronda.schema import Event, Status

log = logging.getLogger("ronda.hub")
router = APIRouter(prefix="/v1")
_events = TypeAdapter(Event | list[Event])
MAX_BATCH = 100


def session_json(s: SessionState) -> dict[str, Any]:
    from ronda.hub.opener import plan

    d = s.model_dump(mode="json", exclude={"status_ts"})
    d["needs_you"] = s.needs_you
    d["source_label"] = labels.source(s.source)
    d["host_label"] = labels.host(s.host.app) if s.host else None
    try:
        p = plan(s)
    except Exception:
        p = None
    d["open_label"] = p.label if p else None  # FR-14
    return d


def snapshot(store) -> dict[str, Any]:
    return {"type": "snapshot", "sessions": [session_json(s) for s in inbox_order(store.sessions())]}


@router.post("/events", status_code=202)
async def post_events(request: Request, body: Any = Body(...)):
    try:
        parsed = _events.validate_python(body)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors(include_url=False, include_input=False)) from None
    events = parsed if isinstance(parsed, list) else [parsed]
    if len(events) > MAX_BATCH:
        raise HTTPException(413, detail=f"at most {MAX_BATCH} events per request")
    st = request.app.state
    accepted = 0
    started, now = time.monotonic(), datetime.now(timezone.utc)
    late = max((now - ev.ts).total_seconds() for ev in events)
    for ev in events:
        prev = await run_in_threadpool(st.store.session, ev.session_id)
        state = await run_in_threadpool(st.store.add_event, ev)
        if state is None:
            continue
        accepted += 1
        st.notifier.maybe(prev, state)
        st.broadcaster.publish({"type": "session", "session": session_json(state),
                                "event": ev.model_dump(mode="json", exclude_none=True)})
    took = time.monotonic() - started
    if took > SLOW_S or late > SLOW_S:
        log.warning("POST /v1/events: %d event(s) sent %.1fs ago, handled in %.2fs", len(events), late, took)
    return {"accepted": accepted, "duplicates": len(events) - accepted}


@router.get("/sessions")
async def get_sessions(request: Request, status: Status | None = None):
    store = request.app.state.store
    sessions = await run_in_threadpool(store.sessions, status)
    return {"sessions": [session_json(s) for s in inbox_order(sessions)]}


@router.get("/sessions/{session_id}/events")
async def get_session_events(request: Request, session_id: str, limit: int = Query(50, ge=1, le=200)):
    store = request.app.state.store
    if await run_in_threadpool(store.session, session_id) is None:
        raise HTTPException(404, detail="no such session")
    events = await run_in_threadpool(store.events, session_id, limit)
    return {"events": [e.model_dump(mode="json", exclude_none=True) for e in events]}


def _refuse(status: int, error: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": error, "message": message, **extra}, status_code=status)


# --- FR-15 snooze, FR-14 open in source ------------------------------------------

FOREVER = timedelta(days=36500)


class SnoozeIn(BaseModel):
    minutes: int | None = Field(default=60, ge=1, le=60 * 24 * 7)  # None: until unmuted


@router.post("/sessions/{session_id}/snooze")
async def snooze(request: Request, session_id: str, body: SnoozeIn):
    st = request.app.state
    until = datetime.now(timezone.utc) + (timedelta(minutes=body.minutes) if body.minutes else FOREVER)
    s = await run_in_threadpool(st.store.set_snooze, session_id, until)
    if s is None:
        raise HTTPException(404, detail="no such session")
    st.broadcaster.publish({"type": "session", "session": session_json(s)})
    return {"snoozed_until": s.snoozed_until.isoformat()}


@router.delete("/sessions/{session_id}/snooze")
async def unsnooze(request: Request, session_id: str):
    st = request.app.state
    s = await run_in_threadpool(st.store.set_snooze, session_id, None)
    if s is None:
        raise HTTPException(404, detail="no such session")
    st.broadcaster.publish({"type": "session", "session": session_json(s)})
    return {"snoozed_until": None}


@router.post("/sessions/{session_id}/open")
async def open_in_source(request: Request, session_id: str):
    """Bring the app where the session runs to the front. Only for this computer, never from Telegram."""
    from ronda.hub import opener

    if request.headers.get("x-ronda-channel") == "telegram":
        raise HTTPException(403, detail="opening apps is only for this computer")
    s = await run_in_threadpool(request.app.state.store.session, session_id)
    if s is None:
        raise HTTPException(404, detail="no such session")
    p = opener.plan(s)
    if p is None:
        return _refuse(409, "cannot_open", "There is no known way to open where this session runs.")
    try:
        await run_in_threadpool(opener.run, p)
    except OSError as e:
        return _refuse(409, "open_failed", f"Could not open it ({type(e).__name__}).")
    return {"opened": p.label}


@router.post("/login-code")
async def login_code(request: Request):
    """A one-time browser login link, for `ronda open`. Bearer token only."""
    if request.scope.get("ronda_auth") != "bearer":
        raise HTTPException(403, detail="bearer token required")
    return {"path": f"/?login={request.app.state.login_codes.issue()}", "valid_s": int(request.app.state.login_codes.TTL_S)}


@router.get("/health")
async def health(request: Request):
    return {"ok": True, "version": __version__, "clients": request.app.state.broadcaster.clients,
            "notify": request.app.state.notifier.enabled}


@router.websocket("/stream")
async def stream(ws: WebSocket):
    app = ws.app
    snap = await run_in_threadpool(snapshot, app.state.store)
    await app.state.broadcaster.serve(ws, snap)
