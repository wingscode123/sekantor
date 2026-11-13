"""The hub: FastAPI app, auth, static web UI and the FR-07 sweep."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ronda import config
from ronda.hub.api import router, session_json
from ronda.hub.notify import Notifier
from ronda.hub.waiters import Waiters
from ronda.hub.auth import LoginCodes, TokenAuthMiddleware, ensure_token
from ronda.hub.store import Store
from ronda.hub.status import sweep
from ronda.schema import Event, Status
from ronda.hub.stream import Broadcaster

SWEEP_EVERY_S = 30
PRUNE_EVERY_S = 3600

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Ronda</title>
<body style="background:#14162B;color:#ECEEF7;font:16px system-ui;padding:40px">
<p>The Ronda hub is running, but the web UI is not built.</p>
<p>Run <code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>, then reload.</p></body>"""


def web_dist() -> Path | None:
    """The built web UI: ``npm run build`` in web/ writes it here, and the wheel ships it."""
    dist = Path(__file__).parent / "static"
    return dist if (dist / "index.html").is_file() else None


def pid_alive(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return True  # unsure: do not end a session we cannot check


def run_sweep(store: Store, broadcaster: Broadcaster, now: datetime | None = None,
              on_change=None) -> int:
    now = now or datetime.now(timezone.utc)
    ended = 0
    for s in store.sessions():
        out = sweep(s, now, pid_alive)
        if out is not None:
            # An event, not just a state change: the timeline and `ronda stats` then see the end too.
            ev = Event(event_id=f"sweep-{now.timestamp():.0f}-{s.session_id}"[:128], ts=now, source=s.source,
                       session_id=s.session_id, type="session_ended", status=Status.ended,
                       summary="Ended: no events for 10 minutes and the process is gone")
            out = store.add_event(ev) or out
            store.expire_actions(out.session_id, None)
            if on_change:
                on_change(out.session_id)
            broadcaster.publish({"type": "session", "session": session_json(out)})
            ended += 1
    return ended


def create_app(home: Path | None = None, port: int | None = None, token: str | None = None,
               settings: config.Settings | None = None, notifier: Notifier | None = None) -> FastAPI:
    home = home or config.home()
    port = port or config.port()
    token = token or ensure_token(home / "token")
    settings = settings or config.settings(home)
    store = Store(home / "ronda.db")
    broadcaster = Broadcaster()
    waiters = Waiters()
    notifier = notifier or Notifier(enabled=settings.notify, quiet=settings.quiet)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def loop():
            ticks = 0
            while True:
                await asyncio.sleep(SWEEP_EVERY_S)
                ticks += 1
                with contextlib.suppress(Exception):
                    loop_ = asyncio.get_running_loop()
                    await asyncio.to_thread(run_sweep, store, broadcaster, None,
                                            lambda sid: loop_.call_soon_threadsafe(waiters.notify, sid))
                    if ticks * SWEEP_EVERY_S % PRUNE_EVERY_S == 0:
                        await asyncio.to_thread(store.prune)
        await asyncio.to_thread(store.prune)
        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            store.close()

    app = FastAPI(title="Ronda hub", version="1", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.store = store
    app.state.broadcaster = broadcaster
    app.state.waiters = waiters
    app.state.notifier = notifier
    app.state.settings = settings
    app.state.login_codes = LoginCodes()
    from ronda.hub import opener as _opener

    app.state.opener_run = _opener.run  # tests replace it
    app.include_router(router)

    dist = web_dist()
    if dist:
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/", include_in_schema=False)
        async def not_built():
            return HTMLResponse(NOT_BUILT)

    app.add_middleware(TokenAuthMiddleware, token=token, port=port, login_codes=app.state.login_codes)
    return app
