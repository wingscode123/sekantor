"""The pos contract: one adapter per platform (PRD "Kontrak pos").

A pos either runs in-process and implements this protocol, or runs as its own process (any
language) and POSTs schema v1 events to ``/v1/events``. ``act`` arrives with M2; a pos declares
what it can do in ``capabilities`` and the UI hides every other button (FR-25).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from ronda.schema import Capability, Event


class Session(BaseModel):
    session_id: str
    source: str
    cwd: str | None = None
    pid: int | None = None


class Action(BaseModel):
    type: Literal["approve", "deny", "reply", "stop", "open"]
    text: str | None = None


@runtime_checkable
class Pos(Protocol):
    name: str
    capabilities: set[Capability]

    def discover(self) -> list[Session]:
        """Sessions running right now (may be empty for push-only pos such as Claude Code hooks)."""
        ...

    def stream(self) -> Iterator[Event]:
        """Yield events as they happen."""
        ...

    def act(self, session_id: str, action: Action) -> None:
        """Carry out an action. Raise NotImplementedError for anything not in ``capabilities``."""
        ...
