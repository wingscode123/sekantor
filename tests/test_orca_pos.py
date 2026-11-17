"""Orca pos over a fake `orca` CLI."""

import json
import subprocess

from sekantor.pos.orca.pos import OrcaTerminals, make_pos


class FakeCli:
    def __init__(self):
        self.terminals = [
            {"handle": "term_a", "agentIdentity": "codex", "connected": True, "writable": True, "orphaned": False,
             "incarnationId": "inc-1", "worktreePath": "D:/work/shop", "tabId": "tab12345xyz", "preview": "thinking..."},
            {"handle": "term_b", "agentIdentity": "claude", "connected": True, "writable": True,
             "incarnationId": "inc-2", "worktreePath": "D:/work/api", "preview": "> "},
            {"handle": "term_c", "agentIdentity": None, "connected": True, "writable": True, "preview": "PS D:\\>"},
        ]
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append(args[1:])
        if args[1:3] == ["terminal", "list"]:
            out = json.dumps({"ok": True, "result": {"terminals": self.terminals}})
        else:
            out = json.dumps({"ok": True, "result": {"accepted": True}})
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")


class FakeHub:
    def __init__(self):
        self.events = []

    def post_event(self, ev):
        self.events.append(ev)
        return True


def test_orca_pos_watches_only_non_claude_agents_and_never_sends():
    cli = FakeCli()
    hub = FakeHub()
    pos = make_pos(hub, OrcaTerminals("orca", runner=cli))
    pos.tick()
    [start] = hub.events
    assert start["session_id"].startswith("orca:term_a:") and start["source"] == "codex"
    assert start["host"]["app"] == "orca" and "process" not in start and start["workspace"]["cwd"] == "D:/work/shop"
    assert sum(1 for c in cli.calls if c[:2] == ["terminal", "list"]) == 1  # one CLI call per cycle
    cli.terminals[0]["preview"] = "patch ready\nApply it? (y/n)"
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_approval" and ev["request"]["kind"] == "tool"
    pos.tick()
    assert not [c for c in cli.calls if c[:2] == ["terminal", "send"]]  # ADR-0021: it only watches


def test_orca_pos_new_run_in_same_terminal_is_a_new_session():
    cli = FakeCli()
    hub = FakeHub()
    pos = make_pos(hub, OrcaTerminals("orca", runner=cli))
    pos.tick()
    first = hub.events[0]["session_id"]
    cli.terminals[0]["incarnationId"] = "inc-9"
    pos.tick()
    assert [e["type"] for e in hub.events[-2:]] == ["session_ended", "session_started"]
    assert hub.events[-1]["session_id"] != first


def test_a_slow_orca_cli_does_not_end_sessions():
    cli = FakeCli()
    hub = FakeHub()
    pos = make_pos(hub, OrcaTerminals("orca", runner=cli))
    pos.tick()

    def timeout(args, **kw):
        raise subprocess.TimeoutExpired(args, 60)

    pos.tmux.runner = timeout
    pos.tick()
    pos.tmux.runner = cli
    pos.tick()
    assert [e["type"] for e in hub.events] == ["session_started"]
