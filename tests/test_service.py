"""ronda service: plans per OS (nothing is installed by the tests)."""

from pathlib import Path

from ronda import service

HOME = Path("/home/u/.ronda")


def test_windows_task_runs_pythonw_without_a_time_limit(tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    p = service.plan(HOME, platform="win32", python=str(py), user="me", scratch=tmp_path)
    [(xml_path, xml)] = p.files.items()
    text = xml.decode("utf-16")
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in text and "<LogonTrigger>" in text
    assert "pythonw.exe" in text and "-m ronda.cli up --no-open --log-file" in text and "<UserId>me</UserId>" in text
    assert p.install == [["schtasks", "/Create", "/TN", "Ronda hub", "/XML", str(xml_path), "/F"]]
    assert p.start == [["schtasks", "/Run", "/TN", "Ronda hub"]]
    assert ["schtasks", "/Delete", "/TN", "Ronda hub", "/F"] in p.uninstall


def test_macos_launch_agent():
    p = service.plan(HOME, platform="darwin", python="/opt/ronda/bin/python")
    [(plist, text)] = p.files.items()
    assert plist.name == "dev.ronda.hub.plist" and "<key>KeepAlive</key><true/>" in text
    assert "<string>/opt/ronda/bin/python</string><string>-m</string><string>ronda.cli</string>" in text
    assert p.install[0][:2] == ["launchctl", "bootstrap"]


def test_linux_systemd_user_unit():
    p = service.plan(HOME, platform="linux", python="/opt/ronda/bin/python")
    [(unit, text)] = p.files.items()
    assert unit.name == "ronda.service" and "Restart=on-failure" in text
    assert "ExecStart=/opt/ronda/bin/python -m ronda.cli up --no-open --log-file" in text
    assert ["systemctl", "--user", "enable", "--now", "ronda.service"] in p.install


def test_up_log_file_option_exists():
    import typer.main

    from ronda.cli import app

    up = typer.main.get_command(app).commands["up"]  # not --help text: CI renders it with colour codes
    assert any("--log-file" in p.opts for p in up.params)
