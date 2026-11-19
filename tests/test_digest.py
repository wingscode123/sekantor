import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from sekantor.cli import app as cli_app
from sekantor.hub import digest
from sekantor.hub.app import create_app
from sekantor.hub.store import Store
from sekantor.schema import Event
from sekantor.stats import compute as stats_compute

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)
TOKEN = "t" * 43
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def ev(i, sid, status, at_min, kind=None, activity=None, cwd="/repo/alpha", summary=None, name="claude"):
    d = {"event_id": f"e{i}", "ts": (NOW - timedelta(minutes=at_min)).isoformat(), "source": "claude-code",
         "session_id": sid, "status": status, "agent": {"name": name, "model": "opus"},
         "workspace": {"cwd": cwd}}
    if kind:
        d["request"] = {"kind": kind}
    if activity:
        d["activity"] = {"tool": "T", "kind": activity}
    if summary:
        d["summary"] = summary
    return Event.model_validate(d)


def seeded(store):
    events = [
        ev(1, "claude:a", "running", 300, activity="read"),                 # before a 4 h window
        ev(2, "claude:a", "running", 200, activity="read"),
        ev(3, "claude:a", "running", 199, activity="read"),
        ev(4, "claude:a", "running", 198, activity="edit"),
        ev(5, "claude:a", "waiting_approval", 190, kind="approval"),
        ev(6, "claude:a", "running", 180, activity="run"),                   # waited 10 min
        ev(7, "claude:a", "reported", 170, kind="report", summary="Refactored the parser"),
        ev(8, "claude:a", "waiting_input", 60, kind="question"),
        ev(9, "claude:a", "running", 50),                                    # waited 10 min
        ev(10, "claude:b", "waiting_approval", 20, kind="approval", cwd="/repo/beta"),  # still waiting
        ev(11, "claude:c", "error", 15, cwd="/repo/alpha"),
        ev(12, "claude:old", "reported", 3000, kind="report"),              # not active in any window here
    ]
    for e in events:
        store.add_event(e)
    return events


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "sekantor.db")
    seeded(s)
    yield s
    s.close()


def by_id(d):
    return {s["session_id"]: s for s in d["sessions"]}


def test_totals_and_rows(store):
    d = digest.compute(store, NOW - timedelta(hours=4), NOW)
    t = d["totals"]
    assert t["agents"] == 3 and "claude:old" not in by_id(d)
    assert t["turns"] == 1 and t["errors"] == 1
    assert t["asked"] == 3                              # approval, question, and the still-open approval
    assert t["wait_s"] == 600 + 600 + 20 * 60           # answered, answered, still waiting
    assert t["longest_wait_s"] == 1200
    assert t["waiting_now"] == 1
    a = by_id(d)["claude:a"]
    assert a["tools"] == {"read": 2, "edit": 1, "run": 1}
    assert a["turns"] == 1 and a["asked"] == 2 and a["wait_s"] == 1200
    assert a["summary"] == "Refactored the parser" and a["status"] == "running"
    assert a["project"]["name"] == "alpha" and a["agent"] == "claude" and a["model"] == "opus"
    assert a["first_at"].startswith("2026-11-19T14:40") and a["last_at"].startswith("2026-11-19T17:10")
    assert by_id(d)["claude:c"]["errors"] == 1


def test_waiting_for_you_first(store):
    d = digest.compute(store, NOW - timedelta(hours=4), NOW)
    assert d["sessions"][0]["session_id"] == "claude:b" and d["sessions"][0]["waiting"] is True
    assert [s["waiting"] for s in d["sessions"]].count(True) == 1


def test_window_clips_waits_and_counts(store):
    d = digest.compute(store, NOW - timedelta(minutes=70), NOW)
    a = by_id(d)["claude:a"]
    assert a["asked"] == 1 and a["wait_s"] == 600 and a["tools"] == {} and a["turns"] == 0


def test_agrees_with_stats(store, tmp_path):
    since = NOW - timedelta(hours=4)
    d = digest.compute(store, since, NOW)
    st = stats_compute(tmp_path, since, NOW)
    answered = sum(st.waiting.values(), timedelta())
    assert d["totals"]["wait_s"] == (answered + st.left_waiting).total_seconds()
    assert d["totals"]["asked"] == sum(len(v) for v in st.answers.values()) + 1  # + the one still open


def test_wait_that_began_before_the_window_counts_from_its_start(store):
    d = digest.compute(store, NOW - timedelta(minutes=10), NOW)
    b = by_id(d)["claude:b"]
    assert b["wait_s"] == 600 and b["asked"] == 1


def test_parse_range():
    now = datetime(2026, 11, 19, 15, 30).astimezone()
    assert digest.parse_range("8h", now) == now - timedelta(hours=8)
    assert digest.parse_range("today", now) == now.replace(hour=0, minute=0, second=0, microsecond=0)
    assert digest.parse_range("2026-11-19T08:00:00+00:00", now) == datetime(2026, 11, 19, 8, tzinfo=timezone.utc)
    assert digest.parse_range("2026-11-19T08:00", now).tzinfo is not None
    with pytest.raises(ValueError):
        digest.parse_range("yesterday-ish", now)


def test_digest_is_fast_on_a_realistic_day(tmp_path):
    s = Store(tmp_path / "big.db")
    base = datetime.now(timezone.utc) - timedelta(hours=10)
    rows = []
    # Mostly tool events (running again and again), with a wait or a finished turn now and then.
    statuses = ["running"] * 3 + ["waiting_approval"] + ["running"] * 8 + ["reported"] + ["running"] * 7 + ["waiting_input"] + ["running"] * 4
    n = 0
    for sess in range(40):
        for k in range(500):
            st = statuses[k % len(statuses)]
            n += 1
            e = {"v": 1, "event_id": f"x{n}", "ts": (base + timedelta(seconds=(sess * 7 + k * 60) % 36000)).isoformat(),
                 "source": "claude-code", "session_id": f"claude:s{sess}", "status": st,
                 "agent": {"name": "claude", "model": "opus"}, "workspace": {"cwd": f"/repo/p{sess % 8}"},
                 "activity": {"tool": "Read", "kind": ["read", "edit", "run", "web"][k % 4]}}
            if st.startswith("waiting"):
                e["request"] = {"kind": "approval" if st == "waiting_approval" else "question"}
            rows.append((e["event_id"], f"claude:s{sess}", e["ts"], e["ts"], json.dumps(e), st,
                         e.get("request", {}).get("kind"), e["activity"]["kind"]))
    s._db.execute("BEGIN")  # one commit, not 20k: keeps the test itself quick
    s._db.executemany("INSERT INTO events(event_id, session_id, ts, received_at, body, status, req_kind, act_kind) "
                      "VALUES (?,?,?,?,?,?,?,?)", rows)
    s._db.execute("COMMIT")
    for sess in range(40):
        s.add_event(Event.model_validate({"event_id": f"z{sess}", "ts": datetime.now(timezone.utc).isoformat(),
                                          "source": "claude-code", "session_id": f"claude:s{sess}", "status": "running"}))
    since = datetime.now(timezone.utc) - timedelta(hours=12)
    times = []
    for _ in range(4):  # the first call warms the page cache; the best of the rest shrugs off a busy machine
        t0 = time.perf_counter()
        d = digest.compute(s, since, datetime.now(timezone.utc))
        times.append(time.perf_counter() - t0)
    took = min(times[1:])
    print(f"digest of {n} events / 40 sessions: {took * 1000:.0f} ms")
    assert d["totals"]["agents"] == 40
    assert took < 0.5  # ~130 ms alone; headroom for a busy machine (the full suite runs alongside)
    s.close()


def test_an_older_database_is_backfilled(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    s = Store(path)
    seeded(s)
    expected = digest.compute(s, NOW - timedelta(hours=4), NOW)
    s.close()
    con = sqlite3.connect(path)  # back to the old shape: no digest columns, no marker
    con.execute("DROP INDEX events_digest")
    for column in ("status", "req_kind", "act_kind"):
        con.execute(f"ALTER TABLE events DROP COLUMN {column}")
    con.execute("DELETE FROM meta WHERE key = 'digest_columns'")
    con.commit()
    con.close()
    s = Store(path)
    got = digest.compute(s, NOW - timedelta(hours=4), NOW)
    assert got["totals"] == expected["totals"] and got["sessions"] == expected["sessions"]
    s.close()


# --- API and CLI ---------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    app = create_app(home=tmp_path, port=7878, token=TOKEN)
    with TestClient(app, base_url="http://127.0.0.1:7878") as c:
        yield c


def test_digest_route(client):
    assert client.get("/v1/digest").status_code == 401
    now = datetime.now(timezone.utc)
    body = {"event_id": "r1", "ts": (now - timedelta(minutes=5)).isoformat(), "source": "claude-code",
            "session_id": "claude:z", "status": "waiting_approval", "request": {"kind": "approval"}}
    assert client.post("/v1/events", headers=AUTH, json=body).status_code == 202
    r = client.get("/v1/digest", headers=AUTH, params={"since": "8h"})
    assert r.status_code == 200
    d = r.json()
    assert d["totals"]["agents"] == 1 and d["totals"]["waiting_now"] == 1
    assert d["sessions"][0]["session_id"] == "claude:z" and d["sessions"][0]["waiting"] is True
    assert client.get("/v1/digest", headers=AUTH).status_code == 200
    assert client.get("/v1/digest", headers=AUTH, params={"since": "garbage"}).status_code == 422


def test_cli_digest_json_and_text(monkeypatch, store):
    d = digest.compute(store, NOW - timedelta(hours=4), NOW)
    seen = {}

    def fake(path, timeout=2.0, **kw):
        seen.update(path=path, timeout=timeout)
        return d

    monkeypatch.setattr("sekantor.cli._api", fake)
    r = CliRunner().invoke(cli_app, ["digest", "--since", "4h", "--json"])
    assert r.exit_code == 0 and json.loads(r.output)["totals"]["agents"] == 3
    assert seen["path"].startswith("/v1/digest?since=") and seen["timeout"] >= 5
    r = CliRunner().invoke(cli_app, ["digest", "--since", "4h"])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert "3 agents" in r.output and "waiting now 1" in r.output
    first_row = next(i for i, line in enumerate(lines) if "claude:b" in line)
    assert not any("claude:a" in line for line in lines[:first_row])
    assert CliRunner().invoke(cli_app, ["digest", "--since", "nope"]).exit_code == 2
