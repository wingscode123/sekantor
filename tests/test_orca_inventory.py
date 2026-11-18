"""Synthetic Orca JSON fixtures use the recorded shapes in docs/spike/orca-workers.md."""

import json
import subprocess
from pathlib import Path

import pytest

from sekantor.pos.orca.pos import OrcaInventory


class FakeInventoryCli:
    def __init__(self):
        file = Path(__file__).parent / "fixtures" / "orca-team-inventory.json"
        self.data = json.loads(file.read_text(encoding="utf-8"))
        self.calls = []
        self.timeout_command = None

    def __call__(self, args, **kwargs):
        command = tuple(args[1:3])
        self.calls.append(args[1:])
        if command == self.timeout_command:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        if command == ("worktree", "ps"):
            response = self.data["worktree_ps"]
        elif command == ("orchestration", "worker-list"):
            response = self.data["worker_list"]
        else:
            assert command == ("orchestration", "dispatch-show")
            response = self.data["dispatch_show"][args[args.index("--task") + 1]]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(response))

    @property
    def workers(self):
        return self.data["worker_list"]["result"]["workers"]


class FakeHub:
    def __init__(self):
        self.events = []

    def post_event(self, event):
        self.events.append(event)
        return True


@pytest.fixture
def inventory():
    clock = [0]
    cli = FakeInventoryCli()
    hub = FakeHub()
    return OrcaInventory("fake-orca", hub, runner=cli, clock=lambda: clock[0]), cli, hub, clock


def test_placements_and_non_claude_sessions(inventory):
    pos, cli, hub, clock = inventory
    pos.tick()
    placements = {e["session_id"]: e["orca"] for e in hub.events if e["type"] == "orca_placement"}
    assert placements["orca-agent:claude_example"] == {
        "session_id": "claude_example", "project": "Sample Project", "worktree": "main",
        "main": True, "model": None, "creator": None,
    }
    assert placements["orca-agent:example_codex"] == {
        "session_id": "example_codex", "project": "Sample Project", "worktree": "codex",
        "main": False, "model": "gpt-6.2-sol", "creator": "claude_example",
    }
    assert placements["orca-agent:example_gemini"]["creator"] == "claude_example"
    assert placements["orca-agent:example_claude"]["creator"] == "claude_example"
    codex, gemini = [e for e in hub.events if e["type"] == "status_changed"]
    assert codex["session_id"] == "orca:ctx_codex"
    assert codex["agent"] == {"name": "codex", "model": "gpt-6.2-sol"}
    assert codex["orca"] == placements["orca-agent:example_codex"]
    assert gemini["session_id"] == "orca:ctx_gemini"
    assert gemini["agent"] == {"name": "gemini", "model": None}
    assert gemini["orca"] == placements["orca-agent:example_gemini"]
    assert codex["status"] == gemini["status"] == "running"
    assert all(e["source"] == "orca" and e["host"]["app"] == "orca" for e in hub.events)
    clock[0] = 14
    pos.tick()
    assert len(hub.events) == 6
    clock[0] = 15
    pos.tick()
    assert len(hub.events) == 10
    assert sum(call[1] == "dispatch-show" for call in cli.calls) == 3


def test_report_failure_disappearance_and_dead_grace(inventory):
    pos, cli, hub, clock = inventory
    pos.tick()
    codex, gemini, _ = cli.workers
    codex["projection"]["stage"]["detail"] = "worker_done"
    gemini["projection"]["outcome"] = "failed"
    gemini["projection"]["liveness"]["verdict"] = "exited"
    clock[0] = 15
    pos.tick()
    assert [event["status"] for event in hub.events[-2:]] == ["reported", "error"]
    assert hub.events[-2]["request"] == {"kind": "report"}
    cli.workers.remove(codex)
    clock[0] = 30
    pos.tick()
    assert (hub.events[-1]["session_id"], hub.events[-1]["type"]) == ("orca:ctx_codex", "session_ended")
    clock[0] = 74
    pos.tick()
    assert hub.events[-1]["type"] == "orca_placement"
    clock[0] = 89
    pos.tick()
    assert (hub.events[-1]["session_id"], hub.events[-1]["type"]) == ("orca:ctx_gemini", "session_ended")
    clock[0] = 104
    pos.tick()
    assert hub.events[-1]["type"] == "orca_placement"


def test_timeout_keeps_last_good_and_backs_off(inventory):
    pos, cli, hub, clock = inventory
    pos.tick()
    cli.timeout_command = ("orchestration", "worker-list")
    clock[0] = 15
    pos.tick()
    assert len(hub.events) == 6
    assert set(pos.workers) == {"ctx_codex", "ctx_gemini"}
    count = len(cli.calls)
    cli.timeout_command = None
    clock[0] = 74
    pos.tick()
    assert len(cli.calls) == count
    clock[0] = 75
    pos.tick()
    assert len(hub.events) == 10


def test_skips_orchestration_without_structured_agents(inventory):
    pos, cli, hub, _ = inventory
    for row in cli.data["worktree_ps"]["result"]["worktrees"]:
        row["agents"] = [{"paneKey": "ordinary:pane", "agentType": "codex"}]
    pos.tick()
    assert [call[:2] for call in cli.calls] == [["worktree", "ps"]]
    assert hub.events == []


def test_dispatch_lookup_rejects_another_dispatch_for_same_task(inventory):
    pos, cli, hub, _ = inventory
    cli.data["dispatch_show"]["task_codex"]["result"]["dispatch"]["id"] = "ctx_retry"
    pos.tick()
    [placement] = [e for e in hub.events if e["session_id"] == "orca-agent:example_codex"]
    assert placement["orca"]["creator"] is None
