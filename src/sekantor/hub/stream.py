"""WebSocket fan-out: every connected UI gets a snapshot, then each session change."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class Broadcaster:
    def __init__(self, max_queue: int = 256):
        self._queues: set[asyncio.Queue] = set()
        self._max = max_queue

    @property
    def clients(self) -> int:
        return len(self._queues)

    def publish(self, message: dict[str, Any]) -> None:
        """Call from the event loop thread. A client that cannot keep up is dropped."""
        for q in list(self._queues):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                self._queues.discard(q)

    async def serve(self, ws: WebSocket, snapshot: dict[str, Any]) -> None:
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue(self._max)
        self._queues.add(q)
        try:
            await ws.send_json(snapshot)
            receiver = asyncio.create_task(self._drain(ws))
            while True:
                getter = asyncio.create_task(q.get())
                done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
                if receiver in done:
                    getter.cancel()
                    break
                await ws.send_json(getter.result())
                if q not in self._queues:  # dropped as too slow
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self._queues.discard(q)
            with contextlib.suppress(Exception):
                await ws.close()

    @staticmethod
    async def _drain(ws: WebSocket) -> None:
        """Read (and ignore) client messages until it disconnects."""
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            while True:
                await ws.receive_text()
