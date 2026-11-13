import json

import pytest
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


@pytest.mark.parametrize("args", [["status"], ["audit"], ["open", "--print"], ["approve", "abc"]])
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


# --- M2: approve / deny / reply / audit against a live hub ----------------------

from ronda.config import Settings
from tests.test_hook_actions import SID, TOKEN, Hub


@pytest.fixture
def hub(tmp_path, monkeypatch):
    (tmp_path / "token").write_text(TOKEN + "\n")
    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    with Hub(tmp_path, Settings()) as h:
        monkeypatch.setenv("RONDA_URL", f"http://127.0.0.1:{h.port}")
        yield h


def _ask(hub, cmd="npm test"):
    hub.call("POST", "/v1/events", {"event_id": "p1", "ts": "2099-01-01T00:00:00+00:00", "source": "claude-code",
                                    "session_id": SID, "status": "waiting_approval", "capabilities": ["approve", "deny"],
                                    "request": {"kind": "tool", "tool": "Bash", "input": cmd, "id": "p1"}})


def test_cli_approve_by_prefix(hub):
    _ask(hub)
    r = runner.invoke(app, ["approve", "ab"])
    assert r.exit_code == 0, r.output
    a = hub.app.state.store.actions(SID)[0]
    assert a["type"] == "approve" and a["channel"] == "cli" and a["request_id"] == "p1"
    out = runner.invoke(app, ["audit"]).output
    assert "approve" in out and "cli" in out


def test_cli_risky_needs_yes(hub):
    _ask(hub, "git push --force")
    r = runner.invoke(app, ["approve", SID], input="n\n")
    assert r.exit_code == 1 and hub.app.state.store.actions(SID) == []
    r = runner.invoke(app, ["approve", SID], input="y\n")
    assert r.exit_code == 0, r.output


def test_cli_refusal_and_unknown(hub):
    _ask(hub)
    r = runner.invoke(app, ["reply", SID, "hello"])
    assert r.exit_code == 1 and "not waiting for a reply" in r.output
    assert runner.invoke(app, ["deny", "zzz"]).exit_code == 2


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
