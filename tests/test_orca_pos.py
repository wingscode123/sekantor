"""Orca pos over a fake `orca` CLI."""

import json
import subprocess

from ronda.pos.orca.pos import OrcaTerminals, make_pos


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
        self.events, self.actions = [], {}

    def post_event(self, ev):
        self.events.append(ev)
        return True

    def next_action(self, sid, kind, rid):
        return self.actions.pop((sid, rid), None)


def test_orca_pos_watches_only_non_claude_agents_and_answers():
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
    assert ev["status"] == "waiting_approval"
    hub.actions[(ev["session_id"], ev["request"]["id"])] = {"type": "approve"}
    pos.tick()
    sends = [c for c in cli.calls if c[:2] == ["terminal", "send"]]
    assert sends == [["terminal", "send", "--terminal", "term_a", "--text", "y", "--json"],
                     ["terminal", "send", "--terminal", "term_a", "--enter", "--json"]]


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
