"""ronda-hook: translation, fingerprinting, and the fail-closed guarantees."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from ronda.pos.claude_code import hook
from ronda.pos.claude_code.fingerprint import classify, load_rules
from ronda.pos.claude_code.translate import git_branch, translate
from ronda.schema import Event

ROOT = Path(__file__).resolve().parents[1]
# The watchdog bounds the hook itself; interpreter start-up on a loaded CI runner or Windows box comes on top.
STARTUP_SLACK_S = 2.0
PAYLOADS = ROOT / "docs" / "spike" / "payloads"
EVIDENCE = ROOT / "docs" / "spike" / "evidence"


def payload(rel: str) -> dict:
    return json.loads((PAYLOADS / rel).read_text(encoding="utf-8"))


# --- translation (real M0 payloads) ---------------------------------------------

@pytest.mark.parametrize(
    "rel, type_, status",
    [
        ("cli-headless/01_SessionStart.json", "session_started", "waiting_input"),
        ("cli-headless/02_UserPromptSubmit.json", "status_changed", "running"),
        ("cli-headless/03_PreToolUse.json", "status_changed", "running"),
        ("cli-headless/10_PermissionRequest.json", "status_changed", "waiting_approval"),
        ("cli-headless/04_PostToolUse.json", "status_changed", "running"),
        ("cli-headless/05_Stop.json", "status_changed", "waiting_input"),
        ("cli-headless/06_SessionEnd.json", "session_ended", "ended"),
        ("orca-terminal/08_Notification.json", "status_changed", "waiting_input"),
        ("claude-desktop/08_SessionStart.json", "session_started", "waiting_input"),
    ],
)
def test_translate_real_payloads(rel, type_, status):
    ev = translate(payload(rel)["stdin"])
    assert ev["type"] == type_ and ev["status"] == status
    assert ev["session_id"].startswith("claude:")
    Event.model_validate(ev)  # every produced event is valid schema v1


def test_permission_request_carries_the_command():
    ev = translate(payload("cli-headless/10_PermissionRequest.json")["stdin"])
    assert ev["request"] == {"kind": "tool", "tool": "PowerShell", "input": "echo ronda-spike > spike-tmp.txt",
                             "id": ev["event_id"]}
    assert ev["summary"] == "Wants to run: echo ronda-spike > spike-tmp.txt"


def test_subagent_stop_is_ignored():
    assert translate(payload("orca-terminal/07_SubagentStop.json")["stdin"]) is None


@pytest.mark.parametrize("kind, status", [("permission_prompt", "waiting_approval"), ("auth_success", None)])
def test_notification_kinds(kind, status):
    ev = translate({"hook_event_name": "Notification", "session_id": "x", "notification_type": kind, "message": "m"})
    assert ev.get("status") == status


def test_stop_failure_is_error():
    ev = translate({"hook_event_name": "StopFailure", "session_id": "x", "error": "rate_limit"})
    assert ev["status"] == "error" and ev["summary"] == "Error: rate_limit"


def test_compact_start_keeps_status():
    ev = translate({"hook_event_name": "SessionStart", "session_id": "x", "source": "compact"})
    assert "status" not in ev and ev["type"] == "session_started"


def test_git_branch(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/feat/ocr\n")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert git_branch(str(sub)) == "feat/ocr"
    wt = tmp_path / "wt"
    wt.mkdir()
    (tmp_path / "wtgit").mkdir()
    (tmp_path / "wtgit" / "HEAD").write_text("0123456789abcdef0123\n")
    (wt / ".git").write_text(f"gitdir: {tmp_path / 'wtgit'}\n")
    assert git_branch(str(wt)) == "0123456789ab"
    assert git_branch(None) is None


# --- fingerprint (M0 evidence) --------------------------------------------------

def test_classify_probe_evidence():
    rules = load_rules()
    probe = json.loads((EVIDENCE / "probe-windows-vscode-orca-terminal-desktop-openbot.json").read_text(encoding="utf-8"))
    got = {}
    for a in probe["agents"]:
        entry = (a.get("env") or {}).get("CLAUDE_CODE_ENTRYPOINT")
        host = classify(rules, a.get("env") or {}, [p["name"] for p in a["parent_chain"]], a["exe"], a["cwd"],
                        " ".join(a["cmdline"] or []))
        got.setdefault(entry, set()).add(host and host["app"])
    assert got["openbot"] == {"openbot"}
    assert got["claude-desktop"] == {"claude-desktop"}
    assert got["sdk-ts"] == {"orca"}
    assert got["cli"] == {"orca"}  # claude run inside an Orca terminal
    assert got["claude-vscode"] == {"vscode"}


def test_classify_env_only_and_fallback():
    rules = load_rules()
    assert classify(rules, {"CLAUDE_CODE_ENTRYPOINT": "claude-vscode"})["app"] == "vscode"
    assert classify(rules, {"TMUX": "/tmp/tmux-1/default,1,0"})["app"] == "tmux"
    assert classify(rules, {}, chain=["zsh", "login"])["app"] == "terminal"
    assert classify(rules, {}) is None


# --- the hook process: fail closed ---------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_hook(home: Path, port: int, stdin: bytes, extra_env=None):
    host_vars = ("ORCA_", "OPENBOT", "CLAUDE", "VSCODE", "TERM_PROGRAM", "TMUX", "WT_SESSION", "CURSOR")
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith(host_vars)}
    env = {**clean, "RONDA_HOME": str(home), "RONDA_URL": f"http://127.0.0.1:{port}", "CLAUDE_PID": str(os.getpid())}
    env.update(extra_env or {})
    t = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "ronda.pos.claude_code.hook"], input=stdin, env=env,
                       capture_output=True, timeout=10)
    return p, time.perf_counter() - t


START = json.dumps({"hook_event_name": "SessionStart", "session_id": "abc", "cwd": str(ROOT), "source": "startup"}).encode()


@pytest.fixture
def home(tmp_path):
    (tmp_path / "token").write_text("tok\n")
    return tmp_path


def test_hub_down_exits_zero_fast_and_silent(home):
    p, dt = run_hook(home, free_port(), START)
    assert p.returncode == 0 and p.stdout == b""
    assert dt < hook.HARD_TIMEOUT_S + STARTUP_SLACK_S
    assert "hub unreachable" in (home / "hook.log").read_text()


def test_hub_hanging_is_cut_by_watchdog(home):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)  # accepts connections, never answers
    try:
        p, dt = run_hook(home, srv.getsockname()[1], START)
    finally:
        srv.close()
    assert p.returncode == 0 and p.stdout == b""
    assert dt < hook.HARD_TIMEOUT_S + STARTUP_SLACK_S


@pytest.mark.parametrize("stdin", [b"", b"not json", b"[1,2]", json.dumps({"hook_event_name": "SubagentStop", "session_id": "x"}).encode()])
def test_garbage_input_is_no_decision(home, stdin):
    p, _ = run_hook(home, free_port(), stdin)
    assert p.returncode == 0 and p.stdout == b""


def test_no_token_is_no_decision(tmp_path):
    p, _ = run_hook(tmp_path, free_port(), START)
    assert p.returncode == 0 and p.stdout == b""
    assert "no token" in (tmp_path / "hook.log").read_text()


def test_hub_up_receives_event(home):
    from ronda.hub.app import create_app

    port = free_port()
    app = create_app(home=home, port=port, token="tok")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        p, _ = run_hook(home, port, START, {"CLAUDE_CODE_ENTRYPOINT": "claude-vscode", "VSCODE_PID": "1"})
        assert p.returncode == 0 and p.stdout == b""
        sessions = app.state.store.sessions()
        assert [s.session_id for s in sessions] == ["claude:abc"]
        s = sessions[0]
        assert s.status.value == "waiting_input" and s.host.app == "vscode" and s.pid == os.getpid()
        assert s.workspace.branch  # this repo is a git checkout
    finally:
        server.should_exit = True
        th.join(5)
