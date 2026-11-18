"""Synthetic Orca JSON fixtures use the recorded shapes in docs/spike/orca-workers.md."""

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from sekantor.pos.orca.pos import OrcaInventory


class FakeInventoryCli:
    def __init__(self):
        file = Path(__file__).parent / "fixtures" / "orca-team-inventory.json"
        self.data = json.loads(file.read_text(encoding="utf-8"))
        self.calls = []
        self.timeout_command = None
        self.bound = False

    def __call__(self, args, **kwargs):
        command = tuple(args[1:3])
        self.calls.append(args[1:])
        if command == self.timeout_command:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        if command == ("worktree", "ps"):
            response = self.data["worktree_ps"]
        elif command == ("orchestration", "worker-list"):
            assert "ORCA_TERMINAL_HANDLE" not in kwargs["env"]
            assert "ORCA_AGENT_SESSION_ID" not in kwargs["env"]
            if self.bound and "--run" not in args:
                response = self.data["bound_worker_list"]
            elif "--run" in args:
                response = {"ok": True, "result": {
                    **self.data["worker_list"]["result"], "scope": {"source": "flag", "run": "run_example"},
                }}
            else:
                response = self.data["worker_list"]
        elif command == ("orchestration", "run-list"):
            response = {"ok": True, "result": {"runs": [{"id": "run_example"}]}}
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
    assert codex["session_id"] == "orca:example_codex"
    assert codex["agent"] == {"name": "codex", "model": "gpt-6.2-sol"}
    assert codex["orca"] == placements["orca-agent:example_codex"]
    assert gemini["session_id"] == "orca:example_gemini"
    assert gemini["agent"] == {"name": "gemini", "model": None}
    assert gemini["orca"] == placements["orca-agent:example_gemini"]
    assert codex["status"] == gemini["status"] == "running"
    assert all(e["source"] == "orca" and e["host"]["app"] == "orca" for e in hub.events)
    clock[0] = 14
    pos.tick()
    assert len(hub.events) == 6
    clock[0] = 15
    pos.tick()
    assert len(hub.events) == 6
    clock[0] = 60
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
    assert (hub.events[-1]["session_id"], hub.events[-1]["type"]) == ("orca:example_codex", "session_ended")
    clock[0] = 74
    pos.tick()
    assert hub.events[-1]["type"] == "orca_placement"
    clock[0] = 89
    pos.tick()
    assert (hub.events[-1]["session_id"], hub.events[-1]["type"]) == ("orca:example_gemini", "session_ended")
    count = len(hub.events)
    clock[0] = 104
    pos.tick()
    assert all(event["type"] == "orca_placement" for event in hub.events[count:])


def test_timeout_keeps_last_good_and_backs_off(inventory):
    pos, cli, hub, clock = inventory
    pos.tick()
    cli.timeout_command = ("orchestration", "worker-list")
    clock[0] = 15
    pos.tick()
    assert len(hub.events) == 6
    assert set(pos.workers) == {"example_codex", "example_gemini"}
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


def test_ends_workers_after_two_complete_empty_sweeps(inventory):
    pos, cli, hub, clock = inventory
    pos.tick()
    cli.data["worktree_ps"]["result"]["worktrees"].clear()
    clock[0] = 15
    pos.tick()
    assert len(hub.events) == 6
    clock[0] = 30
    pos.tick()
    assert {e["session_id"] for e in hub.events if e["type"] == "session_ended"} == {
        "orca:example_codex", "orca:example_gemini",
    }
    assert [call[:2] for call in cli.calls[-2:]] == [["worktree", "ps"]] * 2


def test_follow_up_preserves_original_creator_and_uses_newest_dispatch(inventory):
    pos, cli, hub, clock = inventory
    pos.tick()
    follow = cli.data["follow_up_worker"]
    follow["projection"]["stage"]["activity"] = "done"
    cli.workers.insert(0, follow)
    clock[0] = 15
    pos.tick()
    assert hub.events[-1]["session_id"] == "orca:example_codex"
    assert hub.events[-1]["status"] == "done"
    assert hub.events[-1]["orca"]["creator"] == "claude_example"
    assert hub.events[-1]["agent"]["model"] == "gpt-6.2-sol"
    assert set(pos.workers) == {"example_codex", "example_gemini"}


def test_older_dispatch_lookup_mismatch_preserves_newest_creator(inventory):
    pos, cli, hub, _ = inventory
    follow = cli.data["follow_up_worker"]
    cli.workers.insert(0, follow)
    cli.data["dispatch_show"]["task_codex"] = cli.data["dispatch_show"]["task_follow"]
    pos.tick()
    [codex] = [e for e in hub.events if e["session_id"] == "orca:example_codex"]
    assert codex["orca"]["creator"] == "claude_follow_up_sender"


def test_startup_does_not_replay_old_outcomes_or_create_dead_workers(inventory):
    pos, cli, hub, _ = inventory
    codex, gemini, _ = cli.workers
    codex["projection"]["outcome"] = "succeeded"
    gemini["projection"]["outcome"] = "failed"
    gemini["projection"]["liveness"]["verdict"] = "exited"
    pos.tick()
    [worker] = [e for e in hub.events if e["type"] == "status_changed"]
    assert worker["status"] == "done"
    assert "request" not in worker


def test_bound_inventory_falls_back_to_explicit_runs(inventory, monkeypatch):
    pos, cli, hub, _ = inventory
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "example_terminal")
    monkeypatch.setenv("ORCA_AGENT_SESSION_ID", "example_session")
    cli.bound = True
    pos.tick()
    assert len(hub.events) == 6
    assert any(call[:2] == ["orchestration", "run-list"] for call in cli.calls)
    assert any("--run" in call and "run_example" in call for call in cli.calls)


def test_hub_http_error_backs_off_and_preserves_workers(inventory, monkeypatch):
    pos, cli, hub, clock = inventory
    pos.tick()

    def fail(event):
        raise httpx.ConnectError("hub unavailable")

    monkeypatch.setattr(hub, "post_event", fail)
    cli.workers.clear()
    clock[0] = 15
    pos.tick()
    assert set(pos.workers) == {"example_codex", "example_gemini"}
    assert pos.next_sweep == 75
