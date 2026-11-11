"""Wake long-polling hooks when something changes for their session."""

from __future__ import annotations

import asyncio


class Waiters:
    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def notify(self, session_id: str) -> None:
        ev = self._events.pop(session_id, None)
        if ev is not None:
            ev.set()

    async def wait(self, session_id: str, timeout: float) -> None:
        ev = self._events.setdefault(session_id, asyncio.Event())
        try:
            await asyncio.wait_for(ev.wait(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            pass
