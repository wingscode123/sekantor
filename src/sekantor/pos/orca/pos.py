"""Watch Orca terminals and structured teams through the read-only Orca CLI."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

import httpx

from sekantor.pos.claude_code.translate import new_event_id
from sekantor.pos.hub import connect, poll
from sekantor.pos.tmux.detect import AGENTS, Pane
from sekantor.pos.tmux.pos import TmuxPos

log = logging.getLogger("sekantor.pos.orca")
HOST = {"app": "orca", "confidence": 1.0, "via": ["orca_cli"]}


def orca_cli() -> str | None:
    env = os.environ.get("ORCA_CLI_COMMAND")
    if env and Path(env).exists():
        return env
    found = shutil.which("orca")
    if found:
        return found
    win = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "orca" / "resources" / "bin" / "orca.exe"
    return str(win) if win.exists() else None


class OrcaTerminals:
    """Tmux-shaped transport over the Orca CLI."""

    def __init__(self, cli: str, runner=subprocess.run, timeout: float = 60):
        self.cli = cli
        self.runner = runner
        self.timeout = timeout
        self.preview: dict[str, str] = {}

    def panes(self) -> list[Pane] | None:
        """Agent terminals, or None when the orca CLI did not answer in time."""
        try:
            p = self.runner([self.cli, "terminal", "list", "--json"], capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if p.returncode != 0:
            return []
        try:
            data = json.loads(p.stdout)
        except ValueError:
            return []
        terms = (data.get("result") or data).get("terminals") or []
        panes = []
        self.preview = {}
        for t in terms:
            agent = (t.get("agentIdentity") or "").lower()
            if agent not in AGENTS or not t.get("connected") or not t.get("writable") or t.get("orphaned"):
                continue
            ident = zlib.crc32((t.get("incarnationId") or t["handle"]).encode()) or 1
            self.preview[t["handle"]] = t.get("preview") or ""
            cwd = t.get("worktreePath") or ""
            panes.append(Pane(t["handle"], Path(cwd).name or "orca", (t.get("tabId") or "")[:8], ident, agent, cwd))
        return panes

    def capture(self, handle: str) -> str | None:
        return self.preview.get(handle)


@dataclass(frozen=True)
class Placement:
    project: str
    cwd: str
    main: bool
    agent: str | None

    def block(self, session: str, creator: str | None, model: str | None) -> dict:
        worktree = Path(self.cwd.replace("\\", "/")).name
        return {"session_id": session, "project": self.project, "worktree": worktree,
                "main": self.main, "creator": creator, "model": model}


def normalize_session_id(value: str | None) -> str | None:
    return (value or "").removeprefix("orca_session_id:") or None


def worker_status(row: dict, projection: dict) -> str:
    stage = projection.get("stage") or {}
    outcome = projection.get("outcome")
    worker_state = stage.get("worker") or row.get("workerState")
    if outcome == "failed" or worker_state == "failed":
        return "error"
    if any(state in ("succeeded", "settled", "worker_done")
           for state in (outcome, stage.get("detail"), worker_state)):
        return "reported"
    if (row.get("lastReport") or {}).get("type") == "worker_done":
        return "reported"
    return "running" if stage.get("activity") == "working" else "done"


def recent_completion(value: str | int | None) -> bool:
    try:
        if isinstance(value, (int, float)):
            completed = datetime.fromtimestamp(value / 1000, timezone.utc)
        elif value:
            completed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
        else:
            return False
        return 0 <= (datetime.now(timezone.utc) - completed).total_seconds() <= 600
    except (ValueError, OverflowError, OSError):
        return False


@dataclass(frozen=True)
class Dispatch:
    session: str | None
    creator: str | None
    previous: str | None
    completed_at: str | None


CALLER_ENV = {"ORCA_AGENT_SESSION_ID", "ORCA_AGENT_SESSION_SPAWN_TOKEN",
              "ORCA_TERMINAL_HANDLE", "ORCA_AGENT_PANE"}


class OrcaInventory:
    """Poll structured agents independently of the PTY watcher."""

    def __init__(self, cli: str, hub, runner=subprocess.run, clock=time.monotonic):
        self.cli, self.hub, self.runner, self.clock = cli, hub, runner, clock
        self.next_sweep = 0.0
        self.dispatches: dict[str, Dispatch | None] = {}
        self.active_dispatches: set[str] = set()
        self.placements_sent: dict[str, tuple[dict, float]] = {}
        self.empty_sweeps = 0
        self.workers: dict[str, dict] = {}
        self.dead_since: dict[str, float] = {}

    def _read(self, *args: str) -> dict:
        result = self.runner([self.cli, *args, "--json"], capture_output=True,
                             encoding="utf-8", timeout=12,
                             env={key: value for key, value in os.environ.items() if key not in CALLER_ENV})
        if result.returncode:
            raise ValueError(f"Orca {' '.join(args[:2])} exited with code {result.returncode}")
        envelope = json.loads(result.stdout)
        if envelope.get("ok") is False or not isinstance(envelope.get("result"), dict):
            raise ValueError("Orca inventory response missing result")
        return envelope["result"]

    def _placements(self) -> tuple[dict[str, Placement], bool]:
        data = self._read("worktree", "ps", "--limit", "100")
        truncated = bool(data.get("truncated"))
        if truncated:
            log.warning("Orca worktree inventory truncated at 100 rows")
        placements = {}
        for row in data["worktrees"]:
            for agent in row.get("agents") or []:
                key = agent.get("paneKey") or ""
                if not key.startswith("structured-agent-session-"):
                    continue
                sid, sep, _ = key.removeprefix("structured-agent-session-").rpartition(":")
                sid = normalize_session_id(sid)
                if sep and sid:
                    cwd = row["path"]
                    main = row.get("isMainWorktree")
                    if main is None:
                        main = (Path(cwd) / ".git").is_dir()
                    placements[sid] = Placement(row["repo"], cwd, main, agent.get("agentType"))
        return placements, truncated

    def _pages(self, args, first, next_cursor):
        data = first
        seen = set()
        while True:
            yield data
            cursor = next_cursor(data)
            if cursor is None:
                return
            if not cursor or cursor in seen:
                raise ValueError(f"Orca {' '.join(args[:2])} cursor did not advance")
            seen.add(cursor)
            data = self._read(*args, "--cursor", cursor)

    def _worker_rows(self) -> dict[str, dict]:
        # The concise view omits endpoint incarnation and activity.
        args = ("orchestration", "worker-list", "--full", "--limit", "100")
        first = self._read(*args)
        scope = first["scope"]["source"]
        if scope == "all":
            return self._worker_pages(args, first, "all")
        if scope != "bound":
            raise ValueError(f"Unexpected Orca worker inventory scope: {scope}")
        log.debug("Orca worker inventory is bound to a run, querying each run")
        run_args = ("orchestration", "run-list", "--limit", "100")
        runs = self._pages(run_args, self._read(*run_args), lambda data: data.get("nextCursor"))
        workers = {}
        for page in runs:
            for run in page["runs"]:
                query = (*args, "--run", run["id"])
                workers.update(self._worker_pages(query, self._read(*query), "flag"))
        return workers

    def _worker_pages(self, args, first, scope):
        def next_cursor(data):
            page = data["page"]
            return page.get("nextCursor") or "" if page["hasMore"] else None

        workers = {}
        for data in self._pages(args, first, next_cursor):
            if data["scope"]["source"] != scope or data.get("partialHostErrors"):
                raise ValueError("Orca worker inventory scope changed or is incomplete")
            workers.update((row["dispatchId"], row) for row in data["workers"])
        return workers

    def _emit(self, sid: str, **fields) -> bool:
        return self.hub.post_event({
            "v": 1, "event_id": new_event_id(), "ts": datetime.now(timezone.utc).isoformat(),
            "source": "orca", "host": HOST, "session_id": sid, **fields,
        })

    def _creator(self, key: str) -> str | None:
        creator = None
        visited = set()
        while key and key not in visited and (dispatch := self.dispatches.get(key)):
            visited.add(key)
            creator = dispatch.creator or creator
            key = dispatch.previous
        return creator

    def _resolve(self, rows, placements):
        resolved = {}
        lookups = 0
        for key, row in rows.items():
            resource = row.get("resource") or {}
            kind, _, incarnation = (resource.get("endpointIncarnation") or "").partition(":")
            sid = normalize_session_id(incarnation) if kind == "structured" else None
            if key not in self.dispatches and lookups < 5 and (sid in placements or not sid):
                lookups += 1
                result = self._read("orchestration", "dispatch-show", "--task", row["taskId"], "--full")
                dispatch = result.get("dispatch")
                if dispatch and dispatch["id"] == key:
                    self.dispatches[key] = Dispatch(
                        normalize_session_id(dispatch.get("assignee_orca_session_id")),
                        normalize_session_id(dispatch.get("creator_orca_session_id")),
                        dispatch.get("follow_up_of_dispatch_id"), dispatch.get("completed_at"),
                    )
                else:
                    self.dispatches[key] = None
            dispatch = self.dispatches.get(key)
            assignee = dispatch.session if dispatch else None
            if sid and assignee and sid != assignee:
                continue
            if (sid or assignee) and resource.get("ownerDispatchId") in (None, key):
                resolved[key] = sid or assignee

        # Keep ancestors that a current follow-up can still refer to.
        retained = set(rows)
        for key in rows:
            while (dispatch := self.dispatches.get(key)) and dispatch.previous and dispatch.previous not in retained:
                key = dispatch.previous
                retained.add(key)
        self.dispatches = {key: value for key, value in self.dispatches.items() if key in retained}
        return resolved

    def sweep(self) -> None:
        placements, truncated = self._placements()
        if not placements:
            self.empty_sweeps = 0 if truncated else self.empty_sweeps + 1
            if self.empty_sweeps >= 2:
                for sid in list(self.workers):
                    self._end(sid)
                self.placements_sent.clear()
            return

        self.empty_sweeps = 0
        rows = self._worker_rows()
        resolved = self._resolve(rows, placements)
        self.active_dispatches.intersection_update(rows)

        newest = {}
        metadata = {}
        for key, sid in resolved.items():
            newest.setdefault(sid, key)
            projection = rows[key].get("projection") or {}
            creator, model = metadata.get(sid, (None, None))
            metadata[sid] = (creator or self._creator(key), model or (projection.get("provider") or {}).get("model"))

        now = self.clock()
        for sid, placement in placements.items():
            block = placement.block(sid, *metadata.get(sid, (None, None)))
            previous, sent = self.placements_sent.get(sid, (None, 0))
            if (block != previous or now - sent >= 60) and self._emit(
                f"orca-agent:{sid}", type="orca_placement", orca=block,
            ):
                self.placements_sent[sid] = (block, now)
        if not truncated:
            self.placements_sent = {sid: seen for sid, seen in self.placements_sent.items() if sid in placements}

        for sid in self.workers.keys() - newest.keys():
            self._end(sid)
        for sid, key in newest.items():
            self._update_worker(sid, key, rows[key], placements.get(sid), metadata[sid], now)
        self.dead_since = {sid: since for sid, since in self.dead_since.items() if sid in self.workers}

    def _update_worker(self, sid, key, row, placement, metadata, now):
        projection = row.get("projection") or {}
        verdict = (projection.get("liveness") or {}).get("verdict")
        previous = self.workers.get(sid)
        if verdict in ("dead", "exited"):
            if not previous:
                return
            if now - self.dead_since.setdefault(sid, now) >= 60:
                self._end(sid)
                return
        else:
            self.dead_since.pop(sid, None)

        if placement:
            provider = projection.get("provider") or {}
            agent = (provider.get("id") or placement.agent or "").lower()
            if not agent or agent in ("claude", "claude-code"):
                return
            block = placement.block(sid, *metadata)
            fields = {"agent": {"name": agent, "model": block["model"]},
                      "workspace": {"cwd": placement.cwd}, "orca": block}
        elif previous:
            fields = {name: previous[name] for name in ("agent", "workspace", "orca")}
        else:
            return

        status = worker_status(row, projection)
        if status == "running":
            self.active_dispatches.add(key)
        elif status in ("reported", "error") and key not in self.active_dispatches:
            dispatch = self.dispatches.get(key)
            completed = row.get("completedAt") or (dispatch.completed_at if dispatch else None)
            if not recent_completion(completed):
                status = "done"
        fields["status"] = status
        if status == "reported":
            fields["request"] = {"kind": "report"}
        if fields != previous and self._emit(f"orca:{sid}", type="status_changed", **fields):
            self.workers[sid] = fields

    def _end(self, key: str) -> None:
        if key in self.workers:
            fields = {k: self.workers[key][k] for k in ("agent", "workspace", "orca")}
            if self._emit(f"orca:{key}", type="session_ended", status="ended", **fields):
                del self.workers[key]

    def tick(self) -> None:
        if self.clock() < self.next_sweep:
            return
        delay = 15
        try:
            self.sweep()
        except (httpx.HTTPError, OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, AttributeError) as exc:
            log.warning("Orca inventory sweep failed: %s: %s", type(exc).__name__, exc)
            delay = 60
        finally:
            self.next_sweep = self.clock() + delay


def make_pos(hub, transport: OrcaTerminals) -> TmuxPos:
    def find(pane: Pane):
        return (pane.command, pane.pid) if pane.command in AGENTS else None

    return TmuxPos(transport, hub, find=find, host=HOST, prefix="orca", real_pid=False)


def main(interval: float = 10.0) -> None:
    cli = orca_cli()
    if not cli:
        raise SystemExit("The orca CLI was not found.")
    hub = connect("orca")
    pos = make_pos(hub, OrcaTerminals(cli))
    inventory = OrcaInventory(cli, hub)
    Thread(target=poll, args=(inventory.tick, 1, log), daemon=True).start()
    log.info("watching Orca teams and checking PTY agents every %.0fs", interval)
    poll(pos.tick, interval, log)
