import json

import pytest
import typer.main
from typer.testing import CliRunner

from ronda.cli import app

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
    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    (tmp_path / "token").write_text("x")
    monkeypatch.setenv("RONDA_URL", "http://127.0.0.1:9")
    r = runner.invoke(app, args)
    assert r.exit_code == 1 and "Hub not reachable" in r.output and "ronda up" in r.output


def test_doctor_reports_failures_without_hub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RONDA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("RONDA_URL", "http://127.0.0.1:9")
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 1
    assert "Token missing" in r.output and "Hub not reachable" in r.output


# --- snooze against a live hub --------------------------------------------------

from tests.live_hub import SID, TOKEN, Hub


@pytest.fixture
def hub(tmp_path, monkeypatch):
    (tmp_path / "token").write_text(TOKEN + "\n")
    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    with Hub(tmp_path) as h:
        monkeypatch.setenv("RONDA_URL", f"http://127.0.0.1:{h.port}")
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
    import ronda.cli as cli

    monkeypatch.setattr(cli, "_find_session", lambda ref: {"session_id": "claude:gone"})
    monkeypatch.setattr(cli, "_api", lambda *a, **kw: {"_status": 404, "detail": "no such session"})
    r = runner.invoke(app, ["unsnooze", "gone"])
    assert r.exit_code == 1 and "no such session" in r.output and "Unmuted" not in r.output


def test_service_install_reports_a_file_it_cannot_write(tmp_path, monkeypatch):
    from ronda import service

    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    plan = service.plan(tmp_path)
    plan.files = {blocker / "ronda.xml": "x"}
    monkeypatch.setattr(service, "plan", lambda home: plan)
    r = runner.invoke(app, ["service", "install", "--no-start"])
    assert r.exit_code == 1 and "Could not install the service" in r.output


def test_a_large_service_log_is_rotated_at_start(tmp_path):
    from ronda.cli import _rotate_log

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
