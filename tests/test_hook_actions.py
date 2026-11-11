"""M2: the real ronda-hook process waiting for approve/deny/reply from a live hub (ADR-0008)."""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import pytest
import uvicorn

from ronda.config import Settings
from ronda.hub.app import create_app
from ronda.hub.notify import Notifier
from tests.test_hook import free_port

TOKEN = "tok"
SID = "claude:abc"


class Hub:
    def __init__(self, home, settings):
        self.port = free_port()
        self.app = create_app(home=home, port=self.port, token=TOKEN, settings=settings, notifier=Notifier(enabled=False))
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def session(self):
        return self.app.state.store.session(SID)

    def wait_status(self, status, timeout=10):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = self.session()
            if s and s.status.value == status:
                return s
            time.sleep(0.05)
        raise AssertionError(f"session never reached {status}: {self.session()}")


@pytest.fixture
def home(tmp_path):
    (tmp_path / "token").write_text(TOKEN + "\n")
    return tmp_path


def start_hook(home, port, payload, wait=True, **env_extra):
    host_vars = ("ORCA_", "OPENBOT", "CLAUDE", "VSCODE", "TERM_PROGRAM", "TMUX", "WT_SESSION", "CURSOR")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(host_vars)}
    env.update({"RONDA_HOME": str(home), "RONDA_URL": f"http://127.0.0.1:{port}", **env_extra})
    p = subprocess.Popen([sys.executable, "-m", "ronda.pos.claude_code.hook", *(["--wait"] if wait else [])], env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.stdin.write(json.dumps({"session_id": "abc", "cwd": str(home), **payload}).encode())
    p.stdin.close()
    p.stdin = None  # communicate() must not flush the closed pipe (POSIX)
    return p


PERMISSION = {"hook_event_name": "PermissionRequest", "tool_name": "Bash",
              "tool_input": {"command": "npm test", "description": "Run tests"}}
STOP = {"hook_event_name": "Stop", "last_assistant_message": "Tests pass. Deploy?", "stop_hook_active": False}


@pytest.mark.parametrize("action, behavior", [("approve", "allow"), ("deny", "deny")])
def test_permission_request_gets_the_decision(home, action, behavior):
    with Hub(home, Settings(approval_wait_s=30)) as hub:
        p = start_hook(home, hub.port, PERMISSION)
        s = hub.wait_status("waiting_approval")
        assert s.capabilities == ["approve", "deny"] and s.request.id
        code, body = hub.call("POST", f"/v1/sessions/{SID}/actions", {"type": action, "request_id": s.request.id})
        assert code == 202, body
        out, err = p.communicate(timeout=10)
        assert p.returncode == 0
        decision = json.loads(out)["hookSpecificOutput"]
        assert decision["hookEventName"] == "PermissionRequest" and decision["decision"]["behavior"] == behavior


def test_answered_in_terminal_means_no_decision(home):
    with Hub(home, Settings(approval_wait_s=30)) as hub:
        p = start_hook(home, hub.port, PERMISSION)
        hub.wait_status("waiting_approval")
        t = time.monotonic()
        hub.call("POST", "/v1/events", {"event_id": "post-1", "ts": "2099-01-01T00:00:00+00:00",
                                        "source": "claude-code", "session_id": SID, "status": "running"})
        out, _ = p.communicate(timeout=10)
        assert p.returncode == 0 and out == b""
        assert time.monotonic() - t < 3


def test_approval_wait_runs_out_quietly(home):
    (home / "config.toml").write_text("approval_wait = 2\n")
    with Hub(home, Settings(approval_wait_s=2)) as hub:
        t = time.monotonic()
        p = start_hook(home, hub.port, PERMISSION)
        out, _ = p.communicate(timeout=15)
        assert p.returncode == 0 and out == b""
        assert time.monotonic() - t < 8


def test_approvals_off_no_wait(home):
    (home / "config.toml").write_text("approval_wait = 0\n")
    with Hub(home, Settings(approval_wait_s=0)) as hub:
        t = time.monotonic()
        p = start_hook(home, hub.port, PERMISSION)
        out, _ = p.communicate(timeout=10)
        assert p.returncode == 0 and out == b"" and time.monotonic() - t < 5
        assert hub.session().capabilities == []


def test_hub_down_no_decision(home):
    t = time.monotonic()
    p = start_hook(home, free_port(), PERMISSION)
    out, _ = p.communicate(timeout=10)
    assert p.returncode == 0 and out == b"" and time.monotonic() - t < 5


def test_stop_reply_wakes_agent_with_exit_2(home):
    with Hub(home, Settings()) as hub:
        p = start_hook(home, hub.port, STOP, CLAUDE_CODE_ENTRYPOINT="cli")
        s = hub.wait_status("waiting_input")
        assert s.capabilities == ["reply"] and s.request.kind == "input"
        code, _ = hub.call("POST", f"/v1/sessions/{SID}/actions", {"type": "reply", "text": "Yes, deploy to staging."})
        assert code == 202
        out, err = p.communicate(timeout=10)
        assert p.returncode == 2 and out == b""
        assert err.decode() == "Reply from the user, sent through Ronda:\nYes, deploy to staging."


def test_stop_typed_in_terminal_releases_waiting_hook(home):
    with Hub(home, Settings()) as hub:
        p = start_hook(home, hub.port, STOP, CLAUDE_CODE_ENTRYPOINT="cli")
        hub.wait_status("waiting_input")
        hub.call("POST", "/v1/events", {"event_id": "ups-1", "ts": "2099-01-01T00:00:00+00:00",
                                        "source": "claude-code", "session_id": SID, "status": "running"})
        out, err = p.communicate(timeout=10)
        assert p.returncode == 0 and out == b"" and err == b""


def test_no_reply_offered_in_sdk_hosts(home):
    with Hub(home, Settings()) as hub:
        t = time.monotonic()
        p = start_hook(home, hub.port, STOP, CLAUDE_CODE_ENTRYPOINT="sdk-ts")
        p.communicate(timeout=10)
        assert p.returncode == 0 and time.monotonic() - t < 5
        assert hub.session().capabilities == []


def test_old_install_without_wait_flag_never_waits(home):
    """An M1-shaped install runs these hooks async: it must not offer buttons or take a reply."""
    with Hub(home, Settings()) as hub:
        t = time.monotonic()
        p = start_hook(home, hub.port, STOP, wait=False, CLAUDE_CODE_ENTRYPOINT="cli")
        p.communicate(timeout=10)
        assert p.returncode == 0 and time.monotonic() - t < 5
        assert hub.session().capabilities == []
        p = start_hook(home, hub.port, PERMISSION, wait=False)
        out, _ = p.communicate(timeout=10)
        assert p.returncode == 0 and out == b"" and hub.session().capabilities == []
