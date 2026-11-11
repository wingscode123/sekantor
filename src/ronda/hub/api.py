"""HTTP API v1 (PRD "API hub")."""

from __future__ import annotations

import asyncio
import getpass
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from ronda import __version__
from ronda.config import risky_match
from ronda.hub.status import WAITING, SessionState, inbox_order
from ronda.schema import ActionIn, Event, Status

router = APIRouter(prefix="/v1")
_events = TypeAdapter(Event | list[Event])
MAX_BATCH = 100
MAX_WAIT_S = 30.0

APPROVAL_TYPES = ("approve", "deny")
REPLY_TYPES = ("reply",)


def session_json(s: SessionState) -> dict[str, Any]:
    d = s.model_dump(mode="json", exclude={"status_ts"})
    d["needs_you"] = s.needs_you
    return d


def snapshot(store) -> dict[str, Any]:
    return {"type": "snapshot", "sessions": [session_json(s) for s in inbox_order(store.sessions())]}


def pending_request_id(s: SessionState | None) -> str | None:
    if s is None or s.status not in WAITING or s.request is None:
        return None
    return s.request.id


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
    for ev in events:
        prev = await run_in_threadpool(st.store.session, ev.session_id)
        state = await run_in_threadpool(st.store.add_event, ev)
        if state is None:
            continue
        accepted += 1
        # Answers to a request the session has moved past can never be delivered.
        await run_in_threadpool(st.store.expire_actions, state.session_id, pending_request_id(state))
        st.waiters.notify(state.session_id)
        st.notifier.maybe(prev, state)
        st.broadcaster.publish({"type": "session", "session": session_json(state),
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


# --- actions (ADR-0008) --------------------------------------------------------

def _refuse(status: int, error: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": error, "message": message, **extra}, status_code=status)


def check_action(s: SessionState, body: ActionIn, settings) -> JSONResponse | None:
    """Why this action cannot be accepted now, or None when it can."""
    if body.type in APPROVAL_TYPES:
        if settings.approval_wait_s == 0:
            return _refuse(409, "approvals_off", "Approvals from Ronda are off (approval_wait = 0).")
        if s.status is not Status.waiting_approval or not s.request or s.request.kind != "tool":
            return _refuse(409, "not_waiting", "The session is not waiting for an approval.")
    else:
        if s.status is not Status.waiting_input or not s.request or s.request.kind != "input":
            return _refuse(409, "not_waiting", "The session is not waiting for a reply.")
        if not (body.text or "").strip():
            return _refuse(422, "empty_reply", "Write a reply first.")
    if body.type not in s.capabilities:
        return _refuse(409, "not_supported", f"This session does not accept '{body.type}' from Ronda.")
    if body.request_id and body.request_id != s.request.id:
        return _refuse(409, "stale_request", "That request was already answered or replaced.")
    if body.type == "approve" and not body.confirm:
        pattern = risky_match(s.request.input, settings.risky)
        if pattern:
            return _refuse(409, "confirm_required", "This command matches a risky pattern. Confirm to approve.",
                           pattern=pattern)
    return None


def _channel(request: Request) -> str:
    if request.scope.get("ronda_auth") == "cookie":
        return "web"
    ch = request.headers.get("x-ronda-channel", "api")
    return ch if ch in ("cli", "api") else "api"


@router.post("/sessions/{session_id}/actions", status_code=202)
async def post_action(request: Request, session_id: str, body: ActionIn):
    st = request.app.state
    s = await run_in_threadpool(st.store.session, session_id)
    if s is None:
        raise HTTPException(404, detail="no such session")
    refused = check_action(s, body, st.settings)
    if refused is not None:
        return refused
    text = body.text.strip() if body.text else None
    action = await run_in_threadpool(st.store.add_action, session_id, body.type, s.request.id, text,
                                     _channel(request), getpass.getuser())
    st.waiters.notify(session_id)
    st.broadcaster.publish({"type": "action", "action": action})
    return {"action": action}


@router.get("/sessions/{session_id}/actions/next")
async def next_action(
    request: Request,
    session_id: str,
    request_id: str = Query(..., max_length=128),
    for_: Literal["approval", "reply"] = Query(..., alias="for"),
    wait: float = Query(25.0, ge=0, le=MAX_WAIT_S),
):
    """Long-poll used by hooks: the action for this request, or why there will not be one."""
    st = request.app.state
    types = APPROVAL_TYPES if for_ == "approval" else REPLY_TYPES
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    while True:
        action = await run_in_threadpool(st.store.take_action, session_id, request_id, types)
        if action is not None:
            st.broadcaster.publish({"type": "action", "action": action})
            return {"action": action}
        s = await run_in_threadpool(st.store.session, session_id)
        if pending_request_id(s) != request_id:
            return {"action": None, "reason": "resolved"}
        remaining = deadline - loop.time()
        if remaining <= 0:
            return {"action": None, "reason": "timeout"}
        await st.waiters.wait(session_id, remaining)


@router.get("/sessions/{session_id}/actions")
async def get_session_actions(request: Request, session_id: str, limit: int = Query(100, ge=1, le=1000)):
    return {"actions": await run_in_threadpool(request.app.state.store.actions, session_id, limit)}


@router.get("/actions")
async def get_actions(request: Request, limit: int = Query(100, ge=1, le=1000)):
    """The audit log (FR-24), newest first."""
    return {"actions": await run_in_threadpool(request.app.state.store.actions, None, limit)}


@router.get("/health")
async def health(request: Request):
    s = request.app.state.settings
    return {"ok": True, "version": __version__, "clients": request.app.state.broadcaster.clients,
            "approval_wait": s.approval_wait_s, "reply_wait": s.reply_wait_s, "notify": request.app.state.notifier.enabled}


@router.websocket("/stream")
async def stream(ws: WebSocket):
    app = ws.app
    snap = await run_in_threadpool(snapshot, app.state.store)
    await app.state.broadcaster.serve(ws, snap)
