"""HTTP API v1 (PRD "API hub"). Actions endpoints arrive in M2."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from pydantic import TypeAdapter, ValidationError

from ronda import __version__
from ronda.hub.status import SessionState, inbox_order
from ronda.schema import Event, Status

router = APIRouter(prefix="/v1")
_events = TypeAdapter(Event | list[Event])
MAX_BATCH = 100


def session_json(s: SessionState) -> dict[str, Any]:
    d = s.model_dump(mode="json", exclude={"status_ts"})
    d["needs_you"] = s.needs_you
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
    store, bc = request.app.state.store, request.app.state.broadcaster
    accepted = 0
    for ev in events:
        state = await run_in_threadpool(store.add_event, ev)
        if state is None:
            continue
        accepted += 1
        bc.publish({"type": "session", "session": session_json(state),
                    "event": ev.model_dump(mode="json", exclude_none=True)})
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


@router.get("/health")
async def health(request: Request):
    return {"ok": True, "version": __version__, "clients": request.app.state.broadcaster.clients}


@router.websocket("/stream")
async def stream(ws: WebSocket):
    app = ws.app
    snap = await run_in_threadpool(snapshot, app.state.store)
    await app.state.broadcaster.serve(ws, snap)
