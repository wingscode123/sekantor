import json

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


def test_status_when_hub_down(tmp_path, monkeypatch):
    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    (tmp_path / "token").write_text("x")
    monkeypatch.setenv("RONDA_URL", "http://127.0.0.1:9")
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 1 and "ronda up" in r.output


def test_doctor_reports_failures_without_hub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RONDA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("RONDA_URL", "http://127.0.0.1:9")
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 1
    assert "Token missing" in r.output and "Hub not reachable" in r.output
