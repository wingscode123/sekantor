import json

import pytest
import typer.main
from typer.testing import CliRunner

from sekantor.cli import app

runner = CliRunner()


def test_install_and_uninstall_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["install", "claude", "--project"])
    assert r.exit_code == 0, r.output
    data = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert "SessionStart" in data["hooks"]
    r = runner.invoke(app, ["uninstall", "claude"])
    assert r.exit_code == 0 and "Removed" in r.output
    assert json.loads((tmp_path / ".claude" / "settings.local.json").read_text()) == {}


def test_both_scopes_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["install", "claude", "--project", "--global"]).exit_code == 2


@pytest.mark.parametrize("args", [["status"], ["open", "--print"], ["snooze", "abc"]])
def test_commands_when_hub_down(tmp_path, monkeypatch, args):
    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path))
    (tmp_path / "token").write_text("x")
    monkeypatch.setenv("SEKANTOR_URL", "http://127.0.0.1:9")
    r = runner.invoke(app, args)
    assert r.exit_code == 1 and "Hub not reachable" in r.output and "sekantor up" in r.output


def test_doctor_reports_failures_without_hub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("SEKANTOR_URL", "http://127.0.0.1:9")
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 1
    assert "Token missing" in r.output and "Hub not reachable" in r.output


# --- snooze against a live hub --------------------------------------------------

from tests.live_hub import SID, TOKEN, Hub


@pytest.fixture
def hub(tmp_path, monkeypatch):
    (tmp_path / "token").write_text(TOKEN + "\n")
    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path))
    with Hub(tmp_path) as h:
        monkeypatch.setenv("SEKANTOR_URL", f"http://127.0.0.1:{h.port}")
        yield h


def _ask(hub, cmd="npm test"):
    hub.call("POST", "/v1/events", {"event_id": "p1", "ts": "2099-01-01T00:00:00+00:00", "source": "claude-code",
                                    "session_id": SID, "status": "waiting_approval",
                                    "request": {"kind": "tool", "tool": "Bash", "input": cmd, "id": "p1"}})


@pytest.mark.parametrize("command", ["approve", "deny", "reply", "audit"])
def test_answering_commands_are_gone(command):
    assert runner.invoke(app, [command, "x"]).exit_code == 2


def test_cli_snooze_and_unsnooze(hub):
    _ask(hub)
    r = runner.invoke(app, ["snooze", "ab", "--minutes", "15"])
    assert r.exit_code == 0, r.output
    assert hub.session().snoozed_until is not None
    assert runner.invoke(app, ["unsnooze", "ab"]).exit_code == 0
    assert hub.session().snoozed_until is None


def test_cli_wrong_token_is_not_called_unreachable(hub, tmp_path):
    (tmp_path / "token").write_text("wrong-token-" + "x" * 32)
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 1 and "refused the token" in r.output and "not reachable" not in r.output


def test_cli_unsnooze_reports_a_refusal(monkeypatch):
    import sekantor.cli as cli

    monkeypatch.setattr(cli, "_find_session", lambda ref: {"session_id": "claude:gone"})
    monkeypatch.setattr(cli, "_api", lambda *a, **kw: {"_status": 404, "detail": "no such session"})
    r = runner.invoke(app, ["unsnooze", "gone"])
    assert r.exit_code == 1 and "no such session" in r.output and "Unmuted" not in r.output


def test_service_install_reports_a_file_it_cannot_write(tmp_path, monkeypatch):
    from sekantor import service

    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    plan = service.plan(tmp_path)
    plan.files = {blocker / "sekantor.xml": "x"}
    monkeypatch.setattr(service, "plan", lambda home: plan)
    monkeypatch.setattr(service, "run", lambda commands, check=True: [])
    r = runner.invoke(app, ["service", "install", "--no-start"])
    assert r.exit_code == 1 and "Could not install the service" in r.output


def test_a_large_service_log_is_rotated_at_start(tmp_path):
    from sekantor.cli import _rotate_log

    log = tmp_path / "hub.log"
    log.write_text("x" * 100)
    _rotate_log(log, max_bytes=50)
    assert not log.exists() and (tmp_path / "hub.log.1").read_text() == "x" * 100
    log.write_text("small")
    _rotate_log(log, max_bytes=50)
    assert log.read_text() == "small"


def test_up_has_no_relay_option():
    up = typer.main.get_command(app).commands["up"]
    assert not any("--relay" in p.opts for p in up.params)


def test_no_pair_or_relay_commands():
    names = set(typer.main.get_command(app).commands)
    assert not {"relay", "pair", "unpair"} & names


def test_service_install_waits_for_the_old_hub_to_let_go_of_the_port(tmp_path, monkeypatch):
    import subprocess

    from sekantor import service

    plan = service.plan(tmp_path, platform="win32", user="u")
    plan.files = {}
    calls = []

    def fake_run(commands, check=True):
        calls.extend(c[1] for c in commands)
        return [subprocess.CompletedProcess(c, 0, "", "") for c in commands]

    polls = iter([True, True, False])
    monkeypatch.setattr(service, "plan", lambda home: plan)
    monkeypatch.setattr(service, "run", fake_run)
    monkeypatch.setattr(service, "port_busy", lambda host, port: next(polls, False))
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    r = runner.invoke(app, ["service", "install"])
    assert r.exit_code == 0 and "takes over" not in r.output
    assert calls[-1] == "/Run"  # the new task is started once the port is free
    assert next(polls, "drained") == "drained"


def test_spawned_children_get_no_console_window_on_windows(monkeypatch):
    import subprocess
    import sys

    from sekantor import cli

    seen = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: seen.append(k))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(cli, "_CHILD_OUT", None)
    cli._spawn(["x"], 7878)
    monkeypatch.setattr(cli, "_CHILD_OUT", object())
    cli._spawn(["x"], 7878)
    assert [k["creationflags"] for k in seen] == [0x08000000, 0x08000000]
