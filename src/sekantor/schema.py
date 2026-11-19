"""Event schema v1: the one shape every pos sends to the hub (PRD "Event schema, status & API").

Additions to the PRD example, optional and backward-compatible:
- ``process.pid`` (ADR-0006) for FR-07 liveness checks.
- ``activity`` (ADR-0022): the tool in use and its kind.
- ``subagent`` (ADR-0028): the Claude Code worker that owns a lifecycle or activity event.
- ``orca`` and Orca hook identity (ADR-0029): team placement and identity for Orca sessions.
- ``activity`` events (ADR-0029) update the current tool without requiring a status transition.

Deprecated (ADR-0021: SeKantor watches and does not answer): ``capabilities`` and ``request.id``. They are still
accepted so an older pos keeps working, and are otherwise ignored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1


class Status(str, Enum):
    waiting_approval = "waiting_approval"
    waiting_input = "waiting_input"
    error = "error"
    running = "running"
    reported = "reported"
    done = "done"
    ended = "ended"


EventType = Literal[
    "session_started", "status_changed", "message", "session_ended",
    "subagent_started", "subagent_activity", "subagent_ended", "orca_placement", "activity",
]
SUBAGENT_EVENTS = {"subagent_started", "subagent_activity", "subagent_ended"}
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


class Subagent(_Model):
    id: str = Field(min_length=1)
    type: str | None = None


class Request(_Model):
    kind: Literal["tool", "input", "question", "report", "approval"] = "tool"
    tool: str | None = None
    input: str | None = Field(default=None, max_length=4000)
    subagent: Subagent | None = None
    # Deprecated (ADR-0021): it named the request an answer was for. Accepted, ignored.
    id: str | None = Field(default=None, max_length=128)


class Process(_Model):
    pid: int = Field(gt=0)


class Activity(_Model):
    """What the agent is doing right now (ADR-0022): the tool and its kind."""

    tool: str = Field(max_length=100)
    kind: Literal["read", "edit", "run", "web", "other"]


class OrcaPlacement(_Model):
    session_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    worktree: str = Field(min_length=1)
    main: bool
    creator: str | None = None
    model: str | None = None


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
    capabilities: list[Capability] = Field(default_factory=list)  # deprecated, see the module docstring
    process: Process | None = None
    activity: Activity | None = None
    subagent: Subagent | None = None
    orca: OrcaPlacement | None = None
    orca_session_id: str | None = None
    orca_terminal_handle: str | None = None

    @model_validator(mode="after")
    def _placement_has_metadata(self) -> Event:
        if self.type == "orca_placement" and (self.source != "orca" or self.orca is None):
            raise ValueError("orca_placement requires source orca and placement metadata")
        return self

    @field_validator("ts")
    @classmethod
    def _aware_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
