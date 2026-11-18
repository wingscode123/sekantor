"""Resolve Orca teams from current session and placement data."""

from collections import defaultdict
from dataclasses import dataclass, replace

from sekantor import projects
from sekantor.hub.status import SessionState, Team
from sekantor.schema import OrcaPlacement, Status


def identity(s: SessionState) -> str | None:
    return s.orca_session_id or (s.orca.session_id if s.orca else None)


def placement_key(s: SessionState) -> tuple:
    return s.floor, identity(s), s.workspace.cwd, s.orca


@dataclass(frozen=True)
class Membership:
    team: Team
    names: frozenset[str]
    creator: str | None


class TeamIndex:
    def __init__(self, sessions: dict[str, SessionState], placements: dict[str, OrcaPlacement]):
        self.sessions = sessions
        self.members: dict[str, Membership] = {}
        self.by_project: dict[str, set[str]] = defaultdict(set)
        self.by_identity: dict[str, set[str]] = defaultdict(set)
        for sid, s in sessions.items():
            checkout = projects.checkout(s.workspace.cwd) if s.workspace.cwd else None
            agent_id = identity(s)
            p = placements.get(agent_id) or s.orca
            if p:
                project, worktree, main = p.project, p.worktree, p.main
            elif checkout:
                project, worktree, main = checkout
            else:
                continue
            names = frozenset((project, checkout[0])) if checkout else frozenset((project,))
            team = Team(project, worktree, "lead" if main else "junior", model=p.model if p else None)
            self.members[sid] = Membership(team, names, p.creator if p else None)
            for name in names:
                self.by_project[name].add(sid)
            if agent_id:
                self.by_identity[agent_id].add(sid)

    def peers(self, member: Membership) -> set[str]:
        # A display name and checkout name are aliases when both are known.
        peers = set()
        names = set(member.names)
        while names:
            for candidate in self.by_project[names.pop()] - peers:
                peers.add(candidate)
                names.update(self.members[candidate].names)
        return peers

    def competing_leads(self, sid: str) -> bool:
        member = self.members.get(sid)
        return member is not None and any(
            p != sid and self.members[p].team.role == "lead" and self.sessions[p].status is not Status.ended
            for p in self.peers(member)
        )

    def resolve(self, sid: str) -> Team | None:
        member = self.members.get(sid)
        if member is None or member.team.role == "lead":
            return member.team if member else None
        active = {p for p in self.peers(member) if self.sessions[p].status is not Status.ended}
        leads = {p for p in active if self.members[p].team.role == "lead"}

        def recent(ids: set[str]) -> str | None:
            return max(ids, key=lambda p: (self.sessions[p].last_event_at, p), default=None)

        seen = {sid}
        creator = member.creator
        while creator:
            parent = recent((self.by_identity.get(creator, set()) & active) - seen)
            if parent is None:
                break
            if parent in leads:
                return replace(member.team, lead=parent)
            seen.add(parent)
            creator = self.members[parent].creator
        return replace(member.team, lead=recent(leads))
