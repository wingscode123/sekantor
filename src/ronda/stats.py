"""Dogfooding numbers from local data only (no telemetry): did any event get lost, and how long did
agents wait for you? Reads ~/.ronda/sent.log (what hooks tried to deliver), hook.log and the SQLite db.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

IN_FLIGHT = timedelta(seconds=15)  # attempts this recent may still be on their way
WAITING = {"waiting_approval", "waiting_input"}


@dataclass
class Lost:
    ts: str
    event_id: str
    session_id: str
    label: str


@dataclass
class Stats:
    since: datetime
    until: datetime
    attempted: int = 0
    stored: int = 0
    lost: list[Lost] = field(default_factory=list)  # not stored, with no hub outage to explain it
    lost_hub_down: list[Lost] = field(default_factory=list)  # not stored because the hub was down
    hook_errors: Counter = field(default_factory=Counter)
    sessions: int = 0
    by_host: Counter = field(default_factory=Counter)
    waiting: dict[str, timedelta] = field(default_factory=lambda: {s: timedelta() for s in sorted(WAITING)})
    longest_wait: timedelta = timedelta()
    longest_wait_session: str | None = None


def _parse_ts(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for p in (path.with_name(path.name + ".1"), path):
        try:
            lines += p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
    return lines


def compute(home: Path, since: datetime, until: datetime | None = None) -> Stats:
    until = until or datetime.now(timezone.utc)
    st = Stats(since=since, until=until)

    attempts: dict[str, Lost] = {}
    for line in _read_lines(home / "sent.log"):
        parts = line.split(" ", 3)
        if len(parts) < 4:
            continue
        ts = _parse_ts(parts[0])
        if ts is None or not (since <= ts <= until - IN_FLIGHT):
            continue
        attempts[parts[1]] = Lost(parts[0], parts[1], parts[2], parts[3])
    st.attempted = len(attempts)

    down_at: set[int] = set()  # epoch seconds of "hub unreachable" log lines
    for line in _read_lines(home / "hook.log"):
        try:
            ts = datetime.strptime(line[:19], "%Y-%m-%dT%H:%M:%S").astimezone(timezone.utc)
        except ValueError:
            continue
        if since <= ts <= until:
            message = re.sub(r"^[A-Z][A-Za-z]+: ", "", line[20:].split(" (")[0])  # drop "SessionStart: "
            st.hook_errors[message] += 1
            if message == "hub unreachable":
                down_at.add(int(ts.timestamp()))

    db = home / "ronda.db"
    if not db.exists():
        _split_lost(st, sorted(attempts.values(), key=lambda x: x.ts), down_at)
        return st
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        lo, hi = (since - timedelta(minutes=1)).isoformat(), until.isoformat()
        stored = {r[0] for r in con.execute("SELECT event_id FROM events WHERE ts >= ? AND ts <= ?", (lo, hi))}
        st.stored = len(stored & set(attempts)) if attempts else len(stored)
        _split_lost(st, sorted((a for eid, a in attempts.items() if eid not in stored), key=lambda x: x.ts), down_at)

        rows = con.execute(
            "SELECT session_id, ts, json_extract(body, '$.status'), json_extract(body, '$.host.app') "
            "FROM events WHERE ts <= ? ORDER BY session_id, ts", (hi,)
        ).fetchall()
    finally:
        con.close()

    _waiting(st, rows)
    return st


def _split_lost(st: Stats, lost: list[Lost], down_at: set[int]) -> None:
    """A hook logs "hub unreachable" within a couple of seconds of its event's timestamp."""
    for x in lost:
        ts = _parse_ts(x.ts)
        t = int(ts.timestamp()) if ts else None
        if t is not None and any(t - 1 <= d <= t + 3 for d in down_at):
            st.lost_hub_down.append(x)
        else:
            st.lost.append(x)


def _waiting(st: Stats, rows: list[tuple]) -> None:
    """Sum the time each session spent in a waiting status, clipped to [since, until]."""
    seen_in_window: set[str] = set()
    hosts: dict[str, str] = {}
    current: dict[str, tuple[str, datetime]] = {}
    spans: dict[str, timedelta] = defaultdict(timedelta)

    def close(sid: str, end: datetime) -> None:
        if sid not in current:
            return
        status, start = current[sid]
        if status in WAITING:
            a, b = max(start, st.since), min(end, st.until)
            if b > a:
                st.waiting[status] += b - a
                spans[sid] += b - a
                if b - a > st.longest_wait:
                    st.longest_wait, st.longest_wait_session = b - a, sid

    for sid, ts_text, status, host in rows:
        ts = _parse_ts(ts_text)
        if ts is None:
            continue
        if ts >= st.since:
            seen_in_window.add(sid)
        if host:
            hosts[sid] = host
        if status and (sid not in current or current[sid][0] != status):
            close(sid, ts)
            current[sid] = (status, ts)
    for sid in current:
        close(sid, st.until)

    st.sessions = len(seen_in_window)
    st.by_host = Counter(hosts.get(sid, "unknown") for sid in seen_in_window)


def parse_since(text: str) -> timedelta:
    """'24h', '90m', '7d' -> timedelta."""
    text = text.strip().lower()
    units = {"m": "minutes", "h": "hours", "d": "days"}
    if not text or text[-1] not in units or not text[:-1].isdigit():
        raise ValueError("use a number and m, h or d, e.g. 24h")
    return timedelta(**{units[text[-1]]: int(text[:-1])})
