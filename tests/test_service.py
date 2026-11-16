"""sekantor service: plans per OS (nothing is installed by the tests)."""

from pathlib import Path

from sekantor import service

HOME = Path("/home/u/.sekantor")


def test_windows_task_runs_pythonw_without_a_time_limit(tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    p = service.plan(HOME, platform="win32", python=str(py), user="me", scratch=tmp_path)
    [(xml_path, xml)] = p.files.items()
    text = xml.decode("utf-16")
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in text and "<LogonTrigger>" in text
    assert "pythonw.exe" in text and "-m sekantor.cli up --no-open --log-file" in text and "<UserId>me</UserId>" in text
    assert p.install == [["schtasks", "/Create", "/TN", "SeKantor hub", "/XML", str(xml_path), "/F"]]
    assert p.start == [["schtasks", "/Run", "/TN", "SeKantor hub"]]
    assert ["schtasks", "/Delete", "/TN", "SeKantor hub", "/F"] in p.uninstall


def test_macos_launch_agent():
    p = service.plan(HOME, platform="darwin", python="/opt/sekantor/bin/python")
    [(plist, text)] = p.files.items()
    assert plist.name == "dev.sekantor.hub.plist" and "<key>KeepAlive</key><true/>" in text
    assert "<string>/opt/sekantor/bin/python</string><string>-m</string><string>sekantor.cli</string>" in text
    assert p.install[0][:2] == ["launchctl", "bootstrap"]


def test_linux_systemd_user_unit():
    p = service.plan(HOME, platform="linux", python="/opt/sekantor/bin/python")
    [(unit, text)] = p.files.items()
    assert unit.name == "sekantor.service" and "Restart=on-failure" in text
    assert "ExecStart=/opt/sekantor/bin/python -m sekantor.cli up --no-open --log-file" in text
    assert ["systemctl", "--user", "enable", "--now", "sekantor.service"] in p.install


def test_up_log_file_option_exists():
    import typer.main

    from sekantor.cli import app

    up = typer.main.get_command(app).commands["up"]  # not --help text: CI renders it with colour codes
    assert any("--log-file" in p.opts for p in up.params)


def test_windows_restart_waits_until_the_old_hub_has_let_go_of_the_port(tmp_path):
    # Task Scheduler's End returns before the hub exits; starting at once finds the port busy.
    p = service.plan(HOME, platform="win32", python=str(tmp_path / "python.exe"), user="me", scratch=tmp_path)
    assert p.stop == [["schtasks", "/End", "/TN", "SeKantor hub"]]
    ran, busy = [], iter([True, True, False])
    ok = service.restart(p, busy=lambda: next(busy), run_=lambda cmds, check=True: ran.append(cmds),
                         sleep=lambda s: None)
    assert ok and ran == [p.stop, p.start]


def test_windows_restart_gives_up_when_the_old_hub_does_not_stop(tmp_path):
    p = service.plan(HOME, platform="win32", python=str(tmp_path / "python.exe"), user="me", scratch=tmp_path)
    ran, t = [], [0.0]

    def sleep(s):
        t[0] += s

    ok = service.restart(p, busy=lambda: True, run_=lambda cmds, check=True: ran.append(cmds),
                         wait_s=5, clock=lambda: t[0], sleep=sleep)
    assert not ok and ran == [p.stop]  # never starts a second hub


def test_macos_and_linux_restart_in_one_command():
    mac = service.plan(HOME, platform="darwin", python="/opt/sekantor/bin/python")
    assert mac.restart[0][:3] == ["launchctl", "kickstart", "-k"]
    linux = service.plan(HOME, platform="linux", python="/opt/sekantor/bin/python")
    assert linux.restart == [["systemctl", "--user", "restart", "sekantor.service"]]
    ran = []
    assert service.restart(linux, busy=lambda: True, run_=lambda cmds, check=True: ran.append(cmds))
    assert ran == [linux.restart]


def test_service_install_removes_the_old_ronda_task(tmp_path):
    p = service.plan(HOME, platform="win32", python=str(tmp_path / "python.exe"), user="me", scratch=tmp_path)
    assert ["schtasks", "/End", "/TN", "Ronda hub"] in p.cleanup
    assert ["schtasks", "/Delete", "/TN", "Ronda hub", "/F"] in p.cleanup


def test_old_ronda_units_are_cleaned_up_on_macos_and_linux():
    mac = service.plan(HOME, platform="darwin", python="/p/python")
    assert any("dev.ronda.hub" in c[-1] for c in mac.cleanup)
    lin = service.plan(HOME, platform="linux", python="/p/python")
    assert ["systemctl", "--user", "disable", "--now", "ronda.service"] in lin.cleanup
