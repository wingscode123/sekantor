"""Resolve Orca teams from current session and placement data."""

from dataclasses import dataclass, replace
from typing import Literal

from sekantor import projects
from sekantor.hub.status import SessionState
from sekantor.schema import OrcaPlacement, Status


def floor(s: SessionState) -> Literal["claude", "orca", "openbot"]:
    host = s.host.app if s.host else None
    if "openbot" in (s.source, host):
        return "openbot"
    if "orca" in (s.source, host):
        return "orca"
    return "claude"


@dataclass(frozen=True)
class Team:
    project: str
    worktree: str
    role: Literal["lead", "junior"]
    lead: str | None = None
    model: str | None = None


def _membership(s: SessionState, p: OrcaPlacement | None) -> Team | None:
    if p:
        return Team(p.project, p.worktree, "lead" if p.main else "junior", model=p.model)
    if s.workspace.cwd and (checkout := projects.checkout(s.workspace.cwd)):
        project, worktree, main = checkout
        return Team(project, worktree, "lead" if main else "junior")
    return None


def resolve(sessions: list[SessionState], placements: dict[str, OrcaPlacement]) -> dict[str, Team]:
    memberships = {}
    by_identity = {}
    by_project = {}
    for s in sorted(sessions, key=lambda s: (s.last_event_at, s.session_id)):
        if floor(s) != "orca":
            continue
        identity = s.orca_session_id or (s.orca.session_id if s.orca else None)
        active = s.status is not Status.ended
        if identity and active:
            by_identity[identity] = s.session_id
        p = (placements.get(identity) if identity else None) or s.orca
        team = _membership(s, p)
        if team is None:
            continue
        memberships[s.session_id] = (team, p.creator if p else None)
        if team.role == "lead" and active:
            by_project[team.project] = s.session_id

    result = {}
    for sid, (team, creator) in memberships.items():
        if team.role == "junior":
            lead = by_identity.get(creator)
            if lead is None or lead == sid:
                lead = by_project.get(team.project)
            team = replace(team, lead=lead)
        result[sid] = team
    return result
