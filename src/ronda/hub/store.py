"""SQLite storage for events and derived session state (stdlib sqlite3).

One connection guarded by a lock; FastAPI handlers call it from worker threads.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ronda.hub.status import SessionState, apply
from ronda.schema import Event, Status

RETENTION = timedelta(days=7)
AUDIT_RETENTION = timedelta(days=90)
ACTION_COLS = ("id", "session_id", "request_id", "type", "text", "channel", "actor", "created_at", "outcome", "outcome_at")

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
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    request_id TEXT,
    type TEXT NOT NULL,
    text TEXT,
    channel TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending',
    outcome_at TEXT
);
CREATE INDEX IF NOT EXISTS actions_pending ON actions(session_id, outcome);
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
        with self._lock:
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

    def put_session(self, state: SessionState) -> None:
        with self._lock:
            self._put_session(state)

    def prune(self, now: datetime | None = None) -> int:
        """Delete events past retention and ended sessions with no events left. Returns events deleted."""
        cutoff = ((now or _now()) - RETENTION).isoformat()
        with self._lock:
            n = self._db.execute("DELETE FROM events WHERE received_at < ?", (cutoff,)).rowcount
            audit_cutoff = ((now or _now()) - AUDIT_RETENTION).isoformat()
            self._db.execute("DELETE FROM actions WHERE created_at < ?", (audit_cutoff,))
            self._db.execute(
                "DELETE FROM sessions WHERE status = ? AND updated_at < ? "
                "AND session_id NOT IN (SELECT DISTINCT session_id FROM events)",
                (Status.ended.value, cutoff),
            )
            return n

    # --- actions (the audit log, ADR-0010) ------------------------------------

    def add_action(self, session_id: str, type: str, request_id: str | None, text: str | None,
                   channel: str, actor: str) -> dict:
        now = _now().isoformat()
        with self._lock:
            # A newer answer to the same request replaces an undelivered older one.
            self._db.execute(
                "UPDATE actions SET outcome='superseded', outcome_at=? WHERE session_id=? AND outcome='pending' "
                "AND request_id IS ?", (now, session_id, request_id))
            cur = self._db.execute(
                "INSERT INTO actions(session_id, request_id, type, text, channel, actor, created_at) VALUES (?,?,?,?,?,?,?)",
                (session_id, request_id, type, text, channel, actor, now))
            return self._action(cur.lastrowid)

    def take_action(self, session_id: str, request_id: str, types: tuple[str, ...]) -> dict | None:
        """Hand the oldest pending action for this request to a hook, marking it delivered."""
        now = _now().isoformat()
        marks = ",".join("?" * len(types))
        with self._lock:
            row = self._db.execute(
                f"SELECT id FROM actions WHERE session_id=? AND request_id=? AND outcome='pending' AND type IN ({marks}) "
                "ORDER BY id LIMIT 1", (session_id, request_id, *types)).fetchone()
            if not row:
                return None
            self._db.execute("UPDATE actions SET outcome='delivered', outcome_at=? WHERE id=?", (now, row[0]))
            return self._action(row[0])

    def expire_actions(self, session_id: str, keep_request_id: str | None) -> int:
        """Pending actions for any other request can no longer be delivered."""
        with self._lock:
            return self._db.execute(
                "UPDATE actions SET outcome='expired', outcome_at=? WHERE session_id=? AND outcome='pending' "
                "AND request_id IS NOT ?", (_now().isoformat(), session_id, keep_request_id)).rowcount

    def actions(self, session_id: str | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            select = f"SELECT {','.join(ACTION_COLS)} FROM actions"
            if session_id:
                rows = self._db.execute(f"{select} WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit))
            else:
                rows = self._db.execute(f"{select} ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(zip(ACTION_COLS, r)) for r in rows]

    def _action(self, action_id: int) -> dict:
        row = self._db.execute(f"SELECT {','.join(ACTION_COLS)} FROM actions WHERE id=?", (action_id,)).fetchone()
        return dict(zip(ACTION_COLS, row))

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
