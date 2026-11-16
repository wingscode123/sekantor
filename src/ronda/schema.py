"""Event schema v1: the one shape every pos sends to the hub (PRD "Event schema, status & API").

Additions to the PRD example, both optional and backward-compatible:
- ``process.pid`` (ADR-0006) for FR-07 liveness checks.
- ``activity`` (ADR-0022): the tool in use and its kind.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1


class Status(str, Enum):
    waiting_approval = "waiting_approval"
    waiting_input = "waiting_input"
    error = "error"
    running = "running"
    done = "done"
    ended = "ended"


EventType = Literal["session_started", "status_changed", "message", "session_ended"]
Capability = Literal["approve", "deny", "reply", "stop", "open"]


class _Model(BaseModel):
    # Unknown fields from newer pos are ignored, not rejected.
    model_config = ConfigDict(extra="ignore")


class Agent(_Model):
    name: str
    model: str | None = None


class Workspace(_Model):
    cwd: str | None = None
    branch: str | None = None


class Host(_Model):
    app: str
    confidence: float = Field(ge=0, le=1)
    via: list[str] = Field(default_factory=list)


class Request(_Model):
    kind: Literal["tool", "input", "question"] = "tool"
    tool: str | None = None
    input: str | None = Field(default=None, max_length=4000)
    # ADR-0008: the id actions answer (the asking event's event_id). Optional.
    id: str | None = Field(default=None, max_length=128)


ActionType = Literal["approve", "deny", "reply"]


class ActionIn(_Model):
    """POST /v1/sessions/{id}/actions"""

    type: ActionType
    request_id: str | None = Field(default=None, max_length=128)
    text: str | None = Field(default=None, max_length=4000)
    confirm: bool = False  # second confirmation for risky commands


class Process(_Model):
    pid: int = Field(gt=0)


class Activity(_Model):
    """What the agent is doing right now (ADR-0022): the tool and its kind."""

    tool: str = Field(max_length=100)
    kind: Literal["read", "edit", "run", "web", "other"]


class Event(_Model):
    v: Literal[1] = SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=128)
    ts: datetime
    source: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=256)
    agent: Agent | None = None
    workspace: Workspace | None = None
    host: Host | None = None
    type: EventType = "status_changed"
    status: Status | None = None
    summary: str | None = Field(default=None, max_length=2000)
    request: Request | None = None
    capabilities: list[Capability] = Field(default_factory=list)
    process: Process | None = None
    activity: Activity | None = None

    @field_validator("ts")
    @classmethod
    def _aware_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
