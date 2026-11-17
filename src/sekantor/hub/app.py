"""The hub: FastAPI app, auth, static web UI and the FR-07 sweep."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from sekantor import config
from sekantor.hub.api import router, session_json
from sekantor.hub.notify import Notifier
from sekantor.hub.auth import LoginCodes, TokenAuthMiddleware, ensure_token
from sekantor.hub.store import SLOW_S, Store
from sekantor.hub.status import SessionState, sweep
from sekantor.schema import Event, Status
from sekantor.hub.stream import Broadcaster

log = logging.getLogger("sekantor.hub")
SWEEP_EVERY_S = 30
PRUNE_EVERY_S = 3600

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>SeKantor</title>
<body style="background:#14162B;color:#ECEEF7;font:16px system-ui;padding:40px">
<p>The SeKantor hub is running, but the web UI is not built.</p>
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


def run_sweep(store: Store, now: datetime | None = None) -> list[SessionState]:
    """FR-07: end silent sessions whose process is gone, and return them. Runs in a worker thread."""
    now = now or datetime.now(timezone.utc)
    ended = []
    for s in store.sessions():
        out = sweep(s, now, pid_alive)
        if out is not None:
            # An event, not just a state change: the timeline and `sekantor stats` then see the end too.
            ev = Event(event_id=f"sweep-{now.timestamp():.0f}-{s.session_id}"[:128], ts=now, source=s.source,
                       session_id=s.session_id, type="session_ended", status=Status.ended,
                       summary="Ended: no events for 10 minutes and the process is gone")
            out = store.add_event(ev) or out
            ended.append(out)
    return ended


async def watch_loop(interval: float = 0.5, threshold: float = SLOW_S) -> None:
    """Log when the event loop wakes up late: something blocked it, and every request waited."""
    loop = asyncio.get_running_loop()
    while True:
        start = loop.time()
        await asyncio.sleep(interval)
        late = loop.time() - start - interval
        if late > threshold:
            log.warning("event loop was blocked for %.1fs", late)


async def sweep_tick(store: Store, broadcaster: Broadcaster) -> None:
    """Sweep in a worker thread, then tell stream clients here, on the event loop."""
    for s in await asyncio.to_thread(run_sweep, store):
        broadcaster.publish({"type": "session", "session": session_json(s)})


def write_hook_env(home: Path) -> None:
    """``hook-env.txt``: the env var names the native forwarder may send (every ``env:`` name in the host
    rules, plus CLAUDE_PID), one per line, so a secret in the environment never leaves the process."""
    from sekantor.pos.claude_code.fingerprint import env_names, load_rules

    try:
        names = sorted(env_names(load_rules()) | {"CLAUDE_PID"})
        home.mkdir(parents=True, exist_ok=True)
        tmp = home / f"hook-env.txt.{os.getpid()}"
        tmp.write_bytes("\n".join(names).encode("utf-8") + b"\n")
        os.replace(tmp, home / "hook-env.txt")
    except Exception:
        log.warning("hook-env.txt not written", exc_info=True)


def create_app(home: Path | None = None, port: int | None = None, token: str | None = None,
               settings: config.Settings | None = None, notifier: Notifier | None = None) -> FastAPI:
    home = home or config.home()
    port = port or config.port()
    token = token or ensure_token(home / "token")
    settings = settings or config.settings(home)
    write_hook_env(home)
    store = Store(home / "sekantor.db")
    broadcaster = Broadcaster()
    notifier = notifier or Notifier(enabled=settings.notify, quiet=settings.quiet)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def loop():
            ticks = 0
            while True:
                await asyncio.sleep(SWEEP_EVERY_S)
                ticks += 1
                try:
                    await sweep_tick(store, broadcaster)
                except Exception:
                    log.warning("sweep failed", exc_info=True)
                if ticks * SWEEP_EVERY_S % PRUNE_EVERY_S == 0:
                    try:
                        await asyncio.to_thread(store.prune)
                    except Exception:
                        log.warning("prune failed", exc_info=True)
        await asyncio.to_thread(store.prune)
        tasks = [asyncio.create_task(loop()), asyncio.create_task(watch_loop())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            store.close()

    app = FastAPI(title="SeKantor hub", version="1", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.store = store
    app.state.broadcaster = broadcaster
    app.state.notifier = notifier
    app.state.settings = settings
    app.state.login_codes = LoginCodes()
    app.state.background = set()  # strong refs to fire-and-forget tasks (the SessionStart follow-up)
    app.state.should_exit = False  # set by POST /v1/shutdown; `sekantor up` hands it to uvicorn
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
