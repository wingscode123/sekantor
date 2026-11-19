"""SQLite storage for events and derived session state (stdlib sqlite3).

One connection guarded by a lock; FastAPI handlers call it from worker threads.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sekantor.hub.status import SessionState, apply
from sekantor.hub.teams import TeamIndex, placement_key
from sekantor.schema import Event, OrcaPlacement, Status

log = logging.getLogger("sekantor.hub")
SLOW_S = 1.0  # the hook stops waiting for the hub after 1 s, so anything slower gets a log line
RETENTION = timedelta(days=7)
PLACEMENT_TTL = timedelta(minutes=4)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    received_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, ts);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orca_placements (
    session_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    received_at TEXT NOT NULL,
    body TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=2000")
        self._db.executescript(_SCHEMA)
        self._db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema', '1')")
        self._migrate_digest_columns()
        self._lock = threading.Lock()
        self._orca_sessions = {}
        for (body,) in self._db.execute(
            "SELECT body FROM sessions WHERE json_extract(body, '$.source') = 'orca' "
            "OR json_extract(body, '$.host.app') = 'orca'"
        ):
            s = SessionState.model_validate_json(body)
            if s.floor == "orca":
                self._orca_sessions[s.session_id] = s
        self._team_index: TeamIndex | None = None
        self._team_index_until: datetime | None = None

    def _migrate_digest_columns(self) -> None:
        """Three event fields as plain columns under a covering index, so the daily digest reads a day of
        events from the index alone (no JSON parsing). Older databases get the columns and a one-time backfill."""
        have = {row[1] for row in self._db.execute("PRAGMA table_info(events)")}
        for column in ("status", "req_kind", "act_kind"):
            if column not in have:
                self._db.execute(f"ALTER TABLE events ADD COLUMN {column} TEXT")
        done = self._db.execute("SELECT 1 FROM meta WHERE key = 'digest_columns'").fetchone()
        if not done:
            self._db.execute(
                "UPDATE events SET status = json_extract(body, '$.status'), "
                "req_kind = json_extract(body, '$.request.kind'), act_kind = json_extract(body, '$.activity.kind')"
            )
            self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('digest_columns', '1')")
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS events_digest ON events(ts, session_id, status, req_kind, act_kind)")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- writes ---------------------------------------------------------------

    def add_placement(self, event: Event, received_at: datetime | None = None) -> bool:
        placement = event.orca
        if event.type != "orca_placement" or placement is None:
            raise ValueError("expected an Orca placement event")
        received_at = received_at or _now()
        body = placement.model_dump_json()
        with self._lock:
            previous = self._db.execute(
                "SELECT ts, body FROM orca_placements WHERE session_id = ?", (placement.session_id,),
            ).fetchone()
            ts = event.ts.isoformat()
            newer = previous is None or ts > previous[0]
            changed = previous is None or (newer and body != previous[1])
            self._db.execute(
                "INSERT INTO orca_placements(session_id, event_id, ts, received_at, body) VALUES (?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET event_id=excluded.event_id, ts=excluded.ts, "
                "received_at=MAX(orca_placements.received_at, excluded.received_at), body=excluded.body",
                (placement.session_id, event.event_id, ts if newer else previous[0], received_at.isoformat(),
                 body if newer else previous[1]),
            )
            if changed:
                self._team_index = None
            return changed

    def expire_placements(self, now: datetime | None = None) -> bool:
        cutoff = ((now or _now()) - PLACEMENT_TTL).isoformat()
        with self._lock:
            expired = self._db.execute("DELETE FROM orca_placements WHERE received_at <= ?", (cutoff,)).rowcount > 0
            if expired:
                self._team_index = None
            return expired

    def competing_leads(self, session_id: str) -> bool:
        with self._lock:
            return self._team_index is not None and self._team_index.competing_leads(session_id)

    def add_event(self, event: Event, received_at: datetime | None = None) -> SessionState | None:
        """Store ``event`` and return the updated session, or None if it was a duplicate."""
        if event.type == "orca_placement":
            self.add_placement(event, received_at)
            return None
        received_at = received_at or _now()
        asked = time.monotonic()
        with self._lock:
            got = time.monotonic()
            indexed = False
            previous_indexed = self._orca_sessions.get(event.session_id)
            try:
                self._db.execute("BEGIN IMMEDIATE")
                cur = self._db.execute(
                    "INSERT OR IGNORE INTO events(event_id, session_id, ts, received_at, body, status, req_kind, act_kind) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (event.event_id, event.session_id, event.ts.isoformat(), received_at.isoformat(),
                     event.model_dump_json(exclude_none=True), event.status.value if event.status else None,
                     event.request.kind if event.request else None, event.activity.kind if event.activity else None),
                )
                if cur.rowcount == 0:
                    self._db.execute("ROLLBACK")
                    return None
                previous = self._get_session(event.session_id)
                state = apply(previous, event)
                state.prune_subagents(received_at)
                new_report = state.floor == "orca" and state.status is Status.reported and (
                    previous is None or previous.status is not Status.reported
                    or (state.status_since, state.request) != (previous.status_since, previous.request)
                )
                if new_report:
                    self._index_session(state)
                    indexed = True
                    self._resolve_team(state, received_at)
                    if state.team and state.team.lead:
                        state.reported_to_lead_at = state.status_since
                self._put_session(state)
                self._db.execute("COMMIT")
            except BaseException:
                if indexed:
                    if previous_indexed is None:
                        self._orca_sessions.pop(event.session_id, None)
                    else:
                        self._orca_sessions[event.session_id] = previous_indexed
                    self._team_index = None
                self._db.execute("ROLLBACK")
                raise
            finally:
                done = time.monotonic()
                if done - asked > SLOW_S:
                    log.warning("store.add_event %s: waited %.2fs for the store lock, held it %.2fs",
                                event.event_id, got - asked, done - got)
            if not indexed:
                self._index_session(state)
            return self._resolve_team(state)

    def set_snooze(self, session_id: str, until: datetime | None) -> SessionState | None:
        """Set or clear a session's snooze, keeping the rest of it as stored. None if there is no such session."""
        with self._lock:
            s = self._get_session(session_id)
            if s is not None:
                s.snoozed_until = until
                self._put_session(s)
            return self._resolve_team(s) if s is not None else None

    def acknowledge_report(self, session_id: str) -> SessionState | None:
        """Mark the current report read. Return the resulting session if it exists."""
        with self._lock:
            s = self._get_session(session_id)
            if s is not None:
                self._resolve_team(s)
            if s is not None and s.report_pending:
                s.acknowledged_at = max(_now(), s.status_since)
                self._put_session(s)
            return s

    def prune(self, now: datetime | None = None) -> int:
        """Delete events past retention and ended sessions with no events left. Returns events deleted."""
        cutoff = ((now or _now()) - RETENTION).isoformat()
        with self._lock:
            n = self._db.execute("DELETE FROM events WHERE received_at < ?", (cutoff,)).rowcount
            self._db.execute(
                "DELETE FROM sessions WHERE status = ? AND updated_at < ? "
                "AND session_id NOT IN (SELECT DISTINCT session_id FROM events)",
                (Status.ended.value, cutoff),
            )
            for sid, s in list(self._orca_sessions.items()):
                if s.status is Status.ended and self._get_session(sid) is None:
                    del self._orca_sessions[sid]
                    self._team_index = None
            return n

    # --- reads ----------------------------------------------------------------

    def placements(self, now: datetime | None = None) -> dict[str, OrcaPlacement]:
        cutoff = ((now or _now()) - PLACEMENT_TTL).isoformat()
        with self._lock:
            rows = self._db.execute("SELECT session_id, body FROM orca_placements WHERE received_at > ?", (cutoff,))
            return {session_id: OrcaPlacement.model_validate_json(body) for session_id, body in rows}

    def session(self, session_id: str) -> SessionState | None:
        with self._lock:
            state = self._get_session(session_id)
            if state is not None:
                self._resolve_team(state)
        if state is not None:
            state.prune_subagents(_now())
        return state

    def sessions(self, status: Status | None = None) -> list[SessionState]:
        with self._lock:
            if status is None:
                rows = self._db.execute("SELECT body FROM sessions").fetchall()
            else:
                rows = self._db.execute("SELECT body FROM sessions WHERE status = ?", (status.value,)).fetchall()
            now = _now()
            states = [self._resolve_team(SessionState.model_validate_json(body), now) for (body,) in rows]
        for state in states:
            state.prune_subagents(now)
        return states

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Run a read-only SELECT under the store lock (the digest's windowed read)."""
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def events(self, session_id: str, limit: int = 50) -> list[Event]:
        """The latest ``limit`` events of a session, oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT body FROM events WHERE session_id = ? ORDER BY ts DESC, seq DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [Event.model_validate_json(r[0]) for r in reversed(rows)]

    # --- internals (call with the lock held) ----------------------------------

    def _index_session(self, s: SessionState) -> None:
        previous = self._orca_sessions.get(s.session_id)
        if s.floor == "orca":
            self._orca_sessions[s.session_id] = s
            if previous is None or placement_key(previous) != placement_key(s):
                self._team_index = None
        elif previous is not None:
            del self._orca_sessions[s.session_id]
            self._team_index = None

    def _resolve_team(self, s: SessionState, now: datetime | None = None) -> SessionState:
        s.team_resolved = True
        if s.floor != "orca":
            return s
        now = now or _now()
        if self._team_index is None or (self._team_index_until and now >= self._team_index_until):
            rows = self._db.execute(
                "SELECT session_id, received_at, body FROM orca_placements WHERE received_at > ?",
                ((now - PLACEMENT_TTL).isoformat(),),
            ).fetchall()
            self._team_index_until = min((datetime.fromisoformat(row[1]) + PLACEMENT_TTL for row in rows),
                                         default=None)
            self._team_index = TeamIndex(
                self._orca_sessions, {sid: OrcaPlacement.model_validate_json(body) for sid, _, body in rows},
            )
        s.team = self._team_index.resolve(s.session_id)
        return s

    def _get_session(self, session_id: str) -> SessionState | None:
        row = self._db.execute("SELECT body FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return SessionState.model_validate_json(row[0]) if row else None

    def _put_session(self, s: SessionState) -> None:
        self._db.execute(
            "INSERT INTO sessions(session_id, status, updated_at, body) VALUES (?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, body=excluded.body",
            (s.session_id, s.status.value, _now().isoformat(), s.model_dump_json()),
        )
