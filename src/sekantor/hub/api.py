"""HTTP API v1 (PRD "API hub")."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt, TypeAdapter, ValidationError

from sekantor import __version__, labels, projects
from sekantor.config import Settings
from sekantor.hub.status import SessionState, inbox_order
from sekantor.hub.store import SLOW_S
from sekantor.hub.teams import placement_key
from sekantor.schema import Event, Status

log = logging.getLogger("sekantor.hub")
router = APIRouter(prefix="/v1")
_events = TypeAdapter(Event | list[Event])
MAX_BATCH = 100


def session_json(s: SessionState, settings: Settings | None = None) -> dict[str, Any]:
    from sekantor.hub.opener import plan

    # Action responses may serialize a state loaded directly for a write.
    s = s.model_copy()
    s.prune_subagents(datetime.now(timezone.utc))
    d = s.model_dump(mode="json", exclude={
        "status_ts", "orca", "orca_session_id", "orca_terminal_handle", "reported_to_lead_at",
    })
    floor = s.floor
    if floor == "orca" and not s.team_resolved:
        raise ValueError("Orca session must have its team resolved before serialization")
    project = None
    if floor == "openbot":
        project = {"name": "OpenBot agents", "kind": "other", "signals": []}
    elif s.workspace and s.workspace.cwd:
        project = projects.detect(s.workspace.cwd)
        if settings and (override := settings.projects.get(project["name"])):
            project["kind"] = override
            project["signals"] = ["config.toml: projects"]
    d["project"] = project
    d["needs_you"] = s.needs_you
    d["floor"] = floor
    d["team"] = asdict(s.team) if s.team else None
    d["report_to"] = s.report_to
    d["report_pending"] = s.report_pending
    d["source_label"] = labels.source(s.source)
    d["host_label"] = labels.host(s.host.app) if s.host else None
    try:
        p = plan(s)
    except Exception:
        p = None
    d["open_label"] = p.label if p else None  # FR-14
    return d


def _sessions_json(store, settings: Settings | None, status: Status | None = None) -> list[dict[str, Any]]:
    return [session_json(s, settings) for s in inbox_order(store.sessions(status))]


def snapshot(store, settings: Settings | None = None) -> dict[str, Any]:
    return {"type": "snapshot", "sessions": _sessions_json(store, settings)}


async def publish_session(broadcaster, s: SessionState, settings: Settings | None,
                          event: Event | None = None) -> None:
    if not broadcaster.clients:
        return
    session = await run_in_threadpool(session_json, s, settings)
    msg = {"type": "session", "session": session}
    if event is not None:
        msg["event"] = event.model_dump(mode="json", exclude_none=True)
    broadcaster.publish(msg)


async def publish_snapshot(store, broadcaster, settings: Settings | None) -> None:
    if broadcaster.clients:
        broadcaster.publish(await run_in_threadpool(snapshot, store, settings))


@router.post("/events", status_code=202)
async def post_events(request: Request, body: Any = Body(...)):
    try:
        parsed = _events.validate_python(body)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors(include_url=False, include_input=False, include_context=False)) from None
    events = parsed if isinstance(parsed, list) else [parsed]
    if len(events) > MAX_BATCH:
        raise HTTPException(413, detail=f"at most {MAX_BATCH} events per request")
    st = request.app.state
    accepted = 0
    started, now = time.monotonic(), datetime.now(timezone.utc)
    late = max(((now - ev.ts).total_seconds() for ev in events), default=0)
    refresh_teams = False
    for ev in events:
        if ev.type == "orca_placement":
            refresh_teams |= await run_in_threadpool(st.store.add_placement, ev)
            stored = True
        else:
            stored, affected = await _store_event(st, ev)
            refresh_teams |= affected
        accepted += stored
    if refresh_teams:
        await publish_snapshot(st.store, st.broadcaster, st.settings)
    took = time.monotonic() - started
    if took > SLOW_S or late > SLOW_S:
        log.warning("POST /v1/events: %d event(s) sent %.1fs ago, handled in %.2fs", len(events), late, took)
    return {"accepted": accepted, "duplicates": len(events) - accepted}


# --- the native forwarder: the raw Claude Code hook payload ------------------------------

MAX_HOOK_PAYLOAD = 4 * 1024 * 1024  # what the hook reads from stdin, at most
MAX_HOOK_BODY = MAX_HOOK_PAYLOAD + 256 * 1024  # room for the envelope and the whitelisted env


class HookIn(BaseModel):
    v: StrictInt = Field(ge=1, le=1)
    id: str = Field(min_length=1, max_length=128)
    ts: datetime
    payload: dict[str, Any]
    env: dict[str, str] = {}


async def _store_event(st, ev: Event, notify: bool = True) -> tuple[bool, bool]:
    prev = await run_in_threadpool(st.store.session, ev.session_id)
    state = await run_in_threadpool(st.store.add_event, ev)
    if state is None:
        return False, False
    if notify:
        st.notifier.maybe(prev, state)
    await publish_session(st.broadcaster, state, st.settings, ev)
    if state.floor != "orca" and (prev is None or prev.floor != "orca"):
        return True, False
    if (prev is None or placement_key(prev) != placement_key(state)
            or (prev.status is Status.ended) != (state.status is Status.ended)):
        return True, True
    competing = state.team is not None and state.team.role == "lead" and state.last_event_at != prev.last_event_at
    return True, competing and await run_in_threadpool(st.store.competing_leads, state.session_id)


async def _store(st, ev: Event, notify: bool = True) -> bool:
    stored, refresh_teams = await _store_event(st, ev, notify)
    if refresh_teams:
        await publish_snapshot(st.store, st.broadcaster, st.settings)
    return stored


async def _host_follow_up(st, event: dict, payload: dict, env: dict[str, str]) -> None:
    """SessionStart: the parent chain and agent exe are slow to read, so they follow as a second event."""
    from sekantor.pos.claude_code import hook

    try:
        update = await asyncio.to_thread(hook.host_update, event, payload, env, True)
        if update:
            await _store(st, Event.model_validate(update), notify=False)
    except Exception:
        log.warning("host follow-up failed", exc_info=True)


@router.post("/hooks/claude", status_code=202)
async def post_claude_hook(request: Request):
    """A Claude Code hook payload as the native forwarder sends it; builds the event the Python hook would."""
    if request.scope.get("sekantor_auth") != "bearer":
        raise HTTPException(403, detail="bearer token required")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_HOOK_BODY:
        raise HTTPException(413, detail="hook payload too large")
    raw = await request.body()
    if len(raw) > MAX_HOOK_BODY:
        raise HTTPException(413, detail="hook payload too large")
    try:
        body = HookIn.model_validate_json(raw)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors(include_url=False, include_input=False, include_context=False)) from None
    if len(raw) > MAX_HOOK_PAYLOAD and len(json.dumps(body.payload)) > MAX_HOOK_PAYLOAD:
        raise HTTPException(413, detail="hook payload too large")
    st = request.app.state
    cwd = body.payload.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise HTTPException(422, detail="payload.cwd must be a string")
    if st.settings.ignored(cwd):
        return {"stored": False}  # e.g. OpenBot's own helper runs from its program folder
    from sekantor.pos.claude_code import hook

    try:
        event = await run_in_threadpool(hook.build_event, body.payload, body.env, body.id, body.ts.isoformat())
        if event is None:
            return {"stored": False}
        ev = Event.model_validate(event)
    except (ValidationError, ValueError, TypeError, KeyError):
        raise HTTPException(422, detail="not a Claude Code hook payload") from None
    if not await _store(st, ev):
        return {"stored": False}  # a duplicate event id: nothing new, so no second follow-up
    if event.get("type") == "session_started":
        task = asyncio.create_task(_host_follow_up(st, event, body.payload, body.env))
        st.background.add(task)
        task.add_done_callback(st.background.discard)
    return {"stored": True, "event_id": ev.event_id}


@router.get("/setup")
async def get_setup(request: Request):
    """What `sekantor setup --json` prints, for the desktop app's first run. Bearer token only."""
    if request.scope.get("sekantor_auth") != "bearer":
        raise HTTPException(403, detail="bearer token required")
    from sekantor import cli

    return await run_in_threadpool(cli._setup_report)


@router.get("/sessions")
async def get_sessions(request: Request, status: Status | None = None):
    store = request.app.state.store
    return {"sessions": await run_in_threadpool(_sessions_json, store, request.app.state.settings, status)}


@router.get("/digest")
async def get_digest(request: Request, since: str = "today"):
    """The standup: totals and one row per session active since ``since`` (today, 8h, or an ISO time)."""
    from sekantor.hub import digest

    try:
        start = digest.parse_range(since)
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from None
    st = request.app.state
    return await run_in_threadpool(digest.compute, st.store, start, datetime.now(timezone.utc), st.settings)


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


@router.post("/sessions/{session_id}/acknowledge")
async def acknowledge(request: Request, session_id: str):
    st = request.app.state
    s = await run_in_threadpool(st.store.acknowledge_report, session_id)
    if s is None:
        raise HTTPException(404, detail="no such session")
    if s.status is not Status.reported:
        raise HTTPException(409, detail="session has no report")
    await publish_session(st.broadcaster, s, st.settings)
    return {"acknowledged_at": s.acknowledged_at}


@router.post("/sessions/{session_id}/snooze")
async def snooze(request: Request, session_id: str, body: SnoozeIn):
    st = request.app.state
    until = datetime.now(timezone.utc) + (timedelta(minutes=body.minutes) if body.minutes else FOREVER)
    s = await run_in_threadpool(st.store.set_snooze, session_id, until)
    if s is None:
        raise HTTPException(404, detail="no such session")
    await publish_session(st.broadcaster, s, st.settings)
    return {"snoozed_until": s.snoozed_until.isoformat()}


@router.delete("/sessions/{session_id}/snooze")
async def unsnooze(request: Request, session_id: str):
    st = request.app.state
    s = await run_in_threadpool(st.store.set_snooze, session_id, None)
    if s is None:
        raise HTTPException(404, detail="no such session")
    await publish_session(st.broadcaster, s, st.settings)
    return {"snoozed_until": None}


@router.post("/sessions/{session_id}/open")
async def open_in_source(request: Request, session_id: str):
    """Bring the app where the session runs to the front."""
    from sekantor.hub import opener

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
    """A one-time browser login link, for `sekantor open`. Bearer token only."""
    if request.scope.get("sekantor_auth") != "bearer":
        raise HTTPException(403, detail="bearer token required")
    return {"path": f"/?login={request.app.state.login_codes.issue()}", "valid_s": int(request.app.state.login_codes.TTL_S)}


@router.post("/shutdown", status_code=202)
async def shutdown(request: Request):
    """Ask the hub to exit (`sekantor stop`, the tray's Quit). Bearer token only, like /login-code."""
    if request.scope.get("sekantor_auth") != "bearer":
        raise HTTPException(403, detail="bearer token required")
    request.app.state.should_exit = True
    return {"stopping": True}


@router.get("/health")
async def health(request: Request):
    return {"ok": True, "version": __version__, "clients": request.app.state.broadcaster.clients,
            "notify": request.app.state.notifier.enabled}


@router.websocket("/stream")
async def stream(ws: WebSocket):
    app = ws.app
    snap = await run_in_threadpool(snapshot, app.state.store, app.state.settings)
    await app.state.broadcaster.serve(ws, snap)
