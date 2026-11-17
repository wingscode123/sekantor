"""When the hub is slow, its log says where the time went: a blocked event loop, the store, or a late event."""

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from sekantor.config import Settings
from sekantor.hub import store as store_mod
from sekantor.hub.app import create_app, watch_loop
from sekantor.hub.notify import Notifier
from sekantor.hub.store import Store
from sekantor.schema import Event

TOKEN = "t" * 43
NOW = datetime.now(timezone.utc)


def messages(caplog):
    return [r.getMessage() for r in caplog.records]


def test_a_blocked_event_loop_is_logged(caplog):
    async def main():
        watch = asyncio.create_task(watch_loop(interval=0.05, threshold=0.2))
        await asyncio.sleep(0.1)
        time.sleep(0.5)  # blocks the loop, as a slow synchronous call would
        await asyncio.sleep(0.1)
        watch.cancel()

    asyncio.run(main())
    assert any("event loop was blocked" in m for m in messages(caplog))


def test_a_long_wait_for_the_store_lock_is_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(store_mod, "SLOW_S", 0.2)
    store = Store(tmp_path / "sekantor.db")
    held = threading.Event()

    def hold_lock():
        with store._lock:
            held.set()
            time.sleep(0.5)

    threading.Thread(target=hold_lock).start()
    held.wait()
    store.add_event(Event(event_id="e1", ts=NOW, source="claude-code", session_id="claude:a", status="running"))
    store.close()
    assert any("waited" in m and "store lock" in m for m in messages(caplog))


def test_an_event_that_arrives_late_is_logged(tmp_path, caplog):
    app = create_app(home=tmp_path, port=7878, token=TOKEN, settings=Settings(), notifier=Notifier(enabled=False))
    with TestClient(app, base_url="http://127.0.0.1:7878") as c:
        ev = {"event_id": "e1", "ts": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(), "source": "claude-code",
              "session_id": "claude:a", "status": "running"}
        assert c.post("/v1/events", headers={"Authorization": f"Bearer {TOKEN}"}, json=ev).status_code == 202
    assert any("POST /v1/events" in m and "sent 30" in m for m in messages(caplog))
