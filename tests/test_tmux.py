"""tmux pos (FR-04): detection and events, and a real-tmux run where tmux exists. It only watches (ADR-0021)."""

import shutil
import subprocess
import sys
import textwrap
import time
import uuid

import pytest

from sekantor.pos.tmux.detect import Pane, Watch, agent_of, assess, load_rules, parse_panes
from sekantor.pos.tmux.pos import Tmux, TmuxPos

RULES = load_rules()


def test_parse_panes():
    text = "%1\twork\t0.0\t100\tcodex\t/home/u/shop\n%2\twork\t0.1\t200\tzsh\t/home/u\nbroken line\n"
    panes = parse_panes(text)
    assert [(p.pane_id, p.pid, p.command, p.cwd) for p in panes] == [("%1", 100, "codex", "/home/u/shop"), ("%2", 200, "zsh", "/home/u")]


@pytest.mark.parametrize("name, cmd, agent", [
    ("codex", ["codex"], "codex"),
    ("node", ["node", "/usr/lib/node_modules/@openai/codex/bin/codex.js"], "codex"),
    ("python3", ["python3", "-m", "aider"], "aider"),
    ("python3", ["python3", "/home/u/.local/bin/aider"], "aider"),
    ("node", ["node", "/x/@google/gemini-cli/dist/index.js"], "gemini"),
    ("zsh", ["zsh"], None),
])
def test_agent_of(name, cmd, agent):
    assert agent_of(name, cmd) == agent


def test_assess_states():
    r = RULES["codex"]
    w = Watch(agent="codex", agent_pid=1)
    assert assess(w, "Working on it...\nreading files", r, now=0)[0] == "running"
    assert assess(w, "Working on it...\nreading files", r, now=2)[0] == "running"       # still, no prompt yet
    assert assess(w, "Working on it...\nreading files", r, now=31)[0] == "waiting_input"  # quiet a long time
    w2 = Watch(agent="codex", agent_pid=1)
    assert assess(w2, "Done.\n> ", r, now=0)[0] == "running"
    assert assess(w2, "Done.\n> ", r, now=5)[0] == "waiting_input"                     # at a prompt
    status, rid, prompt, _ = assess(Watch(agent="codex", agent_pid=1), "plan ready\nRun npm test? (y/n)", r, now=0)
    assert status == "waiting_approval" and rid.startswith("tmux-") and "npm test" in prompt


def test_answered_question_higher_up_is_history():
    r = RULES["codex"]
    screen = "Run npm test? (y/n) y\nrunning tests\n.....\nok 1\nok 2\nok 3\nall green"
    assert assess(Watch(agent="codex", agent_pid=1), screen, r, now=0)[0] == "running"


# --- the pos loop with fakes ------------------------------------------------------

class FakeTmux:
    def __init__(self):
        self.screen = {"%1": "starting\n"}
        self.listing = [Pane("%1", "work", "0.0", 100, "codex", "/tmp/shop"), Pane("%2", "work", "0.1", 200, "claude", "/tmp")]

    def panes(self):
        return self.listing

    def capture(self, pane_id):
        return self.screen.get(pane_id, "")


class FakeHub:
    def __init__(self):
        self.events = []

    def post_event(self, ev):
        self.events.append(ev)
        return True


def make(clock):
    agents = {100: ("codex", 1001), 200: ("claude", 2001)}
    hub, tmux = FakeHub(), FakeTmux()
    pos = TmuxPos(tmux, hub, RULES, find=lambda pane: agents.get(pane.pid), clock=lambda: clock[0])
    return pos, tmux, hub, agents


def test_pos_reports_a_waiting_approval():
    clock = [0.0]
    pos, tmux, hub, _ = make(clock)
    pos.tick()
    assert [e["type"] for e in hub.events] == ["session_started"]
    assert hub.events[0]["session_id"] == "tmux:%1:1001" and hub.events[0]["source"] == "codex"  # claude skipped
    tmux.screen["%1"] = "plan ready\nApply the patch? (y/n)"
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_approval" and "capabilities" not in ev
    assert ev["request"]["kind"] == "tool" and "Apply the patch" in ev["request"]["input"]
    assert ev["host"]["app"] == "tmux" and ev["process"] == {"pid": 1001}
    pos.tick()
    assert len(hub.events) == 2  # the same prompt is reported once


def test_pos_reports_waiting_for_input_and_the_end():
    clock = [0.0]
    pos, tmux, hub, agents = make(clock)
    tmux.screen["%1"] = "All done.\n> "
    pos.tick()
    clock[0] = 5
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_input" and ev["request"]["kind"] == "input"
    del agents[100]
    pos.tick()
    assert hub.events[-1]["type"] == "session_ended" and hub.events[-1]["status"] == "ended"


# --- real tmux (Linux/macOS CI; skipped where tmux is missing) --------------------------

FAKE_AGENT = textwrap.dedent("""
    print("planning...", flush=True)
    input("Run the migration? (y/n) ")
""")


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_real_tmux_pane_is_reported_and_left_alone(tmp_path):
    agent_dir = tmp_path / "bin"
    agent_dir.mkdir()
    script = agent_dir / "codex"  # named after an agent: found through the python process's cmdline
    script.write_text(FAKE_AGENT)
    sock = f"sekantor-test-{uuid.uuid4().hex[:8]}"
    tmux = Tmux(extra=["-L", sock])
    subprocess.run(["tmux", "-L", sock, "new-session", "-d", "-s", "t", "-x", "120", "-y", "30",
                    f"{sys.executable} {script}"], check=True)
    try:
        hub = FakeHub()
        pos = TmuxPos(tmux, hub, RULES)
        deadline = time.time() + 15
        while time.time() < deadline:
            pos.tick()
            if hub.events and hub.events[-1].get("status") == "waiting_approval":
                break
            time.sleep(0.3)
        assert hub.events[-1]["status"] == "waiting_approval", hub.events
        assert "Run the migration? (y/n)" in tmux.capture("%0")  # still waiting: nothing was typed
    finally:
        subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)


def test_a_tmux_timeout_does_not_end_sessions():
    lists = iter(["ok", "timeout", "ok"])

    def runner(cmd, **kw):
        if "list-panes" in cmd:
            if next(lists) == "timeout":
                raise subprocess.TimeoutExpired(cmd, 3)
            return subprocess.CompletedProcess(cmd, 0, stdout="%1\twork\t0.0\t100\tcodex\t/tmp/shop\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="thinking\n", stderr="")

    hub = FakeHub()
    pos = TmuxPos(Tmux(runner=runner), hub, RULES, find=lambda pane: ("codex", 1001))
    for _ in range(3):
        pos.tick()
    assert [e["type"] for e in hub.events] == ["session_started"]


def test_no_tmux_server_ends_sessions():
    listing = ["%1\twork\t0.0\t100\tcodex\t/tmp/shop\n"]

    def runner(cmd, **kw):
        if "list-panes" in cmd:
            out = listing.pop() if listing else ""
            return subprocess.CompletedProcess(cmd, 0 if out else 1, stdout=out, stderr="" if out else "no server running")
        return subprocess.CompletedProcess(cmd, 0, stdout="thinking\n", stderr="")

    hub = FakeHub()
    pos = TmuxPos(Tmux(runner=runner), hub, RULES, find=lambda pane: ("codex", 1001))
    pos.tick()
    pos.tick()
    assert [e["type"] for e in hub.events] == ["session_started", "session_ended"]
