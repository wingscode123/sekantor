"""tmux pos (FR-04, FR-23): detection, events, answers, and a real-tmux run where tmux exists."""

import os
import shutil
import subprocess
import sys
import textwrap
import time
import uuid

import pytest

from ronda.pos.tmux.detect import Pane, Watch, agent_of, assess, load_rules, parse_panes
from ronda.pos.tmux.pos import Tmux, TmuxPos

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
        self.sent = []
        self.listing = [Pane("%1", "work", "0.0", 100, "codex", "/tmp/shop"), Pane("%2", "work", "0.1", 200, "claude", "/tmp")]

    def panes(self):
        return self.listing

    def capture(self, pane_id):
        return self.screen.get(pane_id, "")

    def send_keys(self, pane_id, keys):
        self.sent.append((pane_id, "keys", tuple(keys)))
        return True

    def send_text(self, pane_id, text):
        self.sent.append((pane_id, "text", text))
        return True


class FakeHub:
    def __init__(self):
        self.events = []
        self.actions = {}

    def post_event(self, ev):
        self.events.append(ev)
        return True

    def next_action(self, sid, kind, rid):
        return self.actions.pop((sid, rid), None)


def make(clock):
    agents = {100: ("codex", 1001), 200: ("claude", 2001)}
    hub, tmux = FakeHub(), FakeTmux()
    pos = TmuxPos(tmux, hub, RULES, find=lambda pid: agents.get(pid), clock=lambda: clock[0])
    return pos, tmux, hub, agents


def test_pos_reports_approval_and_sends_keys():
    clock = [0.0]
    pos, tmux, hub, _ = make(clock)
    pos.tick()
    assert [e["type"] for e in hub.events] == ["session_started"]
    assert hub.events[0]["session_id"] == "tmux:%1:1001" and hub.events[0]["source"] == "codex"  # claude skipped
    tmux.screen["%1"] = "plan ready\nApply the patch? (y/n)"
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_approval" and ev["capabilities"] == ["approve", "deny"]
    assert ev["request"]["kind"] == "tool" and "Apply the patch" in ev["request"]["input"]
    assert ev["host"]["app"] == "tmux" and ev["process"] == {"pid": 1001}
    hub.actions[("tmux:%1:1001", ev["request"]["id"])] = {"type": "approve"}
    pos.tick()
    assert tmux.sent == [("%1", "keys", ("y", "Enter"))]


def test_pos_reply_and_end():
    clock = [0.0]
    pos, tmux, hub, agents = make(clock)
    tmux.screen["%1"] = "All done.\n> "
    pos.tick()
    clock[0] = 5
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_input" and ev["capabilities"] == ["reply"]
    hub.actions[("tmux:%1:1001", ev["request"]["id"])] = {"type": "reply", "text": "now run the linter"}
    pos.tick()
    assert tmux.sent == [("%1", "text", "now run the linter")]
    del agents[100]
    pos.tick()
    assert hub.events[-1]["type"] == "session_ended" and hub.events[-1]["status"] == "ended"


def test_pos_refuses_to_type_into_a_pane_whose_agent_changed():
    clock = [0.0]
    pos, tmux, hub, agents = make(clock)
    pos.tick()
    agents[100] = ("codex", 9999)  # a new codex in the same pane
    assert pos.act("tmux:%1:1001", {"type": "reply", "text": "hi"}) is False
    assert tmux.sent == []


# --- real tmux (Linux/macOS CI; skipped where tmux is missing) --------------------------

FAKE_AGENT = textwrap.dedent("""
    import sys
    print("planning...", flush=True)
    answer = input("Run the migration? (y/n) ")
    with open(sys.argv[1], "w") as f:
        f.write(answer)
    print("ok, done", flush=True)
    input("> ")
""")


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
def test_real_tmux_pane(tmp_path):
    from ronda.pos.tmux.pos import find_agent

    agent_dir = tmp_path / "bin"
    agent_dir.mkdir()
    script = agent_dir / "codex"  # named after an agent: found through the python process's cmdline
    script.write_text(FAKE_AGENT)
    out = tmp_path / "answer.txt"
    sock = f"ronda-test-{uuid.uuid4().hex[:8]}"
    tmux = Tmux(extra=["-L", sock])
    subprocess.run(["tmux", "-L", sock, "new-session", "-d", "-s", "t", "-x", "120", "-y", "30",
                    f"{sys.executable} {script} {out}"], check=True)
    try:
        hub = FakeHub()
        pos = TmuxPos(tmux, hub, RULES, find=find_agent)
        deadline = time.time() + 15
        while time.time() < deadline:
            pos.tick()
            if hub.events and hub.events[-1].get("status") == "waiting_approval":
                break
            time.sleep(0.3)
        ev = hub.events[-1]
        assert ev["status"] == "waiting_approval", hub.events
        hub.actions[(ev["session_id"], ev["request"]["id"])] = {"type": "approve"}
        pos.tick()
        for _ in range(50):
            if out.exists():
                break
            time.sleep(0.1)
        assert out.read_text() == "y"
    finally:
        subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)
