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


class OrcaInventory:
    """Poll structured agents independently of the PTY watcher."""

    def __init__(self, cli: str, hub, runner=subprocess.run, clock=time.monotonic):
        self.cli, self.hub, self.runner, self.clock = cli, hub, runner, clock
        self.next_sweep = 0.0
        self.dispatches: dict[str, tuple[str | None, str | None]] = {}
        self.workers: dict[str, dict] = {}
        self.dead_since: dict[str, float] = {}

    def _read(self, *args: str) -> dict:
        result = self.runner([self.cli, *args, "--json"], capture_output=True,
                             encoding="utf-8", timeout=12)
        if result.returncode:
            raise ValueError("Orca inventory command failed")
        envelope = json.loads(result.stdout)
        if envelope.get("ok") is False or not isinstance(envelope.get("result"), dict):
            raise ValueError("Orca inventory response missing result")
        return envelope["result"]

    def _placements(self) -> dict[str, Placement]:
        data = self._read("worktree", "ps", "--limit", "100")
        if data.get("truncated") and data["totalCount"] > 100:
            data = self._read("worktree", "ps", "--limit", str(data["totalCount"]))
        if data.get("truncated"):
            raise ValueError("Orca worktree inventory truncated")
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
        return placements

    def _worker_rows(self) -> dict[str, dict]:
        args = ("orchestration", "worker-list", "--full", "--limit", "100")
        cursor_args: tuple[str, ...] = ()
        seen_cursors = set()
        workers = {}
        while True:
            data = self._read(*args, *cursor_args)
            if (data.get("scope") or {}).get("source") != "all":
                raise ValueError("Orca worker inventory is scoped to a run")
            workers.update((row["dispatchId"], row) for row in data["workers"])
            page = data["page"]
            if not page["hasMore"]:
                return workers
            cursor = page["nextCursor"]
            if not cursor or cursor in seen_cursors:
                raise ValueError("Orca worker inventory cursor did not advance")
            seen_cursors.add(cursor)
            cursor_args = ("--cursor", cursor)

    def _emit(self, sid: str, **fields) -> bool:
        return self.hub.post_event({
            "v": 1, "event_id": new_event_id(), "ts": datetime.now(timezone.utc).isoformat(),
            "source": "orca", "host": HOST, "session_id": sid, **fields,
        })

    def sweep(self) -> None:
        placements = self._placements()
        if not placements:
            return

        rows = self._worker_rows()
        self.dispatches = {key: value for key, value in self.dispatches.items() if key in rows}
        resolved: dict[str, tuple[str, str | None]] = {}
        metadata: dict[str, tuple[str | None, str | None]] = {}
        lookups = 0
        for key, row in rows.items():
            projection = row.get("projection") or {}
            resource = row.get("resource") or {}
            if resource.get("ownerDispatchId") not in (None, key):
                continue
            kind, _, incarnation = (resource.get("endpointIncarnation") or "").partition(":")
            sid = normalize_session_id(incarnation) if kind == "structured" else None
            if key not in self.dispatches and lookups < 5 and (sid in placements or not sid):
                lookups += 1
                dispatch = self._read("orchestration", "dispatch-show", "--task", row["taskId"], "--full")["dispatch"]
                if dispatch["id"] == key:
                    self.dispatches[key] = (normalize_session_id(dispatch.get("assignee_orca_session_id")),
                                            normalize_session_id(dispatch.get("creator_orca_session_id")))
                else:
                    # Exact identity is required even when a task has a newer dispatch.
                    self.dispatches[key] = (None, None)
            assignee, creator = self.dispatches.get(key, (None, None))
            if sid and assignee and sid != assignee:
                continue
            sid = sid or assignee
            if sid:
                resolved[key] = (sid, creator)
                metadata[sid] = (creator, (projection.get("provider") or {}).get("model"))

        for sid, placement in placements.items():
            creator, model = metadata.get(sid, (None, None))
            self._emit(f"orca-agent:{sid}", type="orca_placement", orca=placement.block(sid, creator, model))

        now = self.clock()
        self.dead_since = {key: since for key, since in self.dead_since.items() if key in rows}
        for key, row in rows.items():
            projection = row.get("projection") or {}
            verdict = (projection.get("liveness") or {}).get("verdict")
            if verdict in ("dead", "exited"):
                self.dead_since.setdefault(key, now)
                if now - self.dead_since[key] >= 60:
                    self._end(key)
                    continue
            else:
                self.dead_since.pop(key, None)

            sid, creator = resolved.get(key, (None, None))
            placement = placements.get(sid)
            if placement:
                provider = projection.get("provider") or {}
                agent = (provider.get("id") or placement.agent or "").lower()
                if not agent or agent in ("claude", "claude-code"):
                    continue
                model = provider.get("model")
                fields = {"agent": {"name": agent, "model": model}, "workspace": {"cwd": placement.cwd},
                          "orca": placement.block(sid, creator, model)}
            elif key in self.workers:
                fields = {k: self.workers[key][k] for k in ("agent", "workspace", "orca")}
            else:
                continue
            status = worker_status(row, projection)
            fields["status"] = status
            if status == "reported":
                fields["request"] = {"kind": "report"}
            if fields != self.workers.get(key) and self._emit(f"orca:{key}", type="status_changed", **fields):
                self.workers[key] = fields

        for key in self.workers.keys() - rows.keys():
            self._end(key)

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
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, AttributeError) as exc:
            log.warning("Orca inventory sweep failed: %s", type(exc).__name__)
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
