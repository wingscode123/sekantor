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
from sekantor.schema import Event, Status

log = logging.getLogger("sekantor.hub")
SLOW_S = 1.0  # the hook stops waiting for the hub after 1 s, so anything slower gets a log line
RETENTION = timedelta(days=7)

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
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- writes ---------------------------------------------------------------

    def add_event(self, event: Event, received_at: datetime | None = None) -> SessionState | None:
        """Store ``event`` and return the updated session, or None if it was a duplicate."""
        received_at = received_at or _now()
        asked = time.monotonic()
        with self._lock:
            got = time.monotonic()
            try:
                self._db.execute("BEGIN IMMEDIATE")
                cur = self._db.execute(
                    "INSERT OR IGNORE INTO events(event_id, session_id, ts, received_at, body) VALUES (?,?,?,?,?)",
                    (event.event_id, event.session_id, event.ts.isoformat(), received_at.isoformat(),
                     event.model_dump_json(exclude_none=True)),
                )
                if cur.rowcount == 0:
                    self._db.execute("ROLLBACK")
                    return None
                state = apply(self._get_session(event.session_id), event)
                self._put_session(state)
                self._db.execute("COMMIT")
                return state
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            finally:
                done = time.monotonic()
                if done - asked > SLOW_S:
                    log.warning("store.add_event %s: waited %.2fs for the store lock, held it %.2fs",
                                event.event_id, got - asked, done - got)

    def set_snooze(self, session_id: str, until: datetime | None) -> SessionState | None:
        """Set or clear a session's snooze, keeping the rest of it as stored. None if there is no such session."""
        with self._lock:
            s = self._get_session(session_id)
            if s is not None:
                s.snoozed_until = until
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
            return n

    # --- reads ----------------------------------------------------------------

    def session(self, session_id: str) -> SessionState | None:
        with self._lock:
            return self._get_session(session_id)

    def sessions(self, status: Status | None = None) -> list[SessionState]:
        with self._lock:
            if status is None:
                rows = self._db.execute("SELECT body FROM sessions").fetchall()
            else:
                rows = self._db.execute("SELECT body FROM sessions WHERE status = ?", (status.value,)).fetchall()
        return [SessionState.model_validate_json(r[0]) for r in rows]

    def events(self, session_id: str, limit: int = 50) -> list[Event]:
        """The latest ``limit`` events of a session, oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT body FROM events WHERE session_id = ? ORDER BY ts DESC, seq DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [Event.model_validate_json(r[0]) for r in reversed(rows)]

    # --- internals (call with the lock held) ----------------------------------

    def _get_session(self, session_id: str) -> SessionState | None:
        row = self._db.execute("SELECT body FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return SessionState.model_validate_json(row[0]) if row else None

    def _put_session(self, s: SessionState) -> None:
        self._db.execute(
            "INSERT INTO sessions(session_id, status, updated_at, body) VALUES (?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, body=excluded.body",
            (s.session_id, s.status.value, _now().isoformat(), s.model_dump_json()),
        )
