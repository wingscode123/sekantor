"""`ronda service`: start the hub at login, so it is not off for hours (dogfooding 2026-11-11).

Windows: a Task Scheduler task (XML, so it has no 3-day run limit and restarts on failure) running
`pythonw -m ronda.cli up --no-open --log-file ~/.ronda/hub.log` with no console window.
macOS: a launchd agent (RunAtLoad, KeepAlive). Linux: a systemd user unit.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

TASK = "Ronda hub"
LABEL = "dev.ronda.hub"


@dataclass
class Plan:
    files: dict[Path, str | bytes] = field(default_factory=dict)  # file -> content to write
    install: list[list[str]] = field(default_factory=list)         # commands to run after writing
    start: list[list[str]] = field(default_factory=list)
    stop: list[list[str]] = field(default_factory=list)            # Windows: restart = stop, wait, start
    restart: list[list[str]] = field(default_factory=list)         # macOS, Linux: one command
    uninstall: list[list[str]] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    remove: list[Path] = field(default_factory=list)


def hub_command(home: Path, platform: str = sys.platform, python: str = sys.executable) -> list[str]:
    if platform == "win32":
        exe = Path(python)
        w = exe.with_name("pythonw.exe")  # no console window
        exe = w if w.exists() or not exe.exists() else exe
        return [str(exe), "-m", "ronda.cli", "up", "--no-open", "--log-file", str(home / "hub.log")]
    return [python, "-m", "ronda.cli", "up", "--no-open", "--log-file", (home / "hub.log").as_posix()]


def _windows_xml(cmd: list[str], user: str) -> bytes:
    args = " ".join(f'"{a}"' if " " in a else a for a in cmd[1:])
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Ronda hub: one inbox for your coding agents (127.0.0.1:7878)</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>10</Count></RestartOnFailure>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(cmd[0])}</Command><Arguments>{escape(args)}</Arguments></Exec></Actions>
</Task>
"""
    return xml.encode("utf-16")


def _launchd_plist(cmd: list[str], home: Path) -> str:
    args = "".join(f"<string>{escape(a)}</string>" for a in cmd)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>{args}</array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>{escape((home / "hub.log").as_posix())}</string>
</dict></plist>
"""


def _systemd_unit(cmd: list[str]) -> str:
    return f"""[Unit]
Description=Ronda hub (one inbox for your coding agents)
After=default.target

[Service]
ExecStart={" ".join(cmd)}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def plan(home: Path, platform: str = sys.platform, python: str = sys.executable,
         user: str | None = None, scratch: Path | None = None) -> Plan:
    cmd = hub_command(home, platform, python)
    p = Plan()
    if platform == "win32":
        user = user or os.environ.get("USERNAME", "")
        xml = (scratch or home) / "ronda-task.xml"
        p.files[xml] = _windows_xml(cmd, user)
        p.install = [["schtasks", "/Create", "/TN", TASK, "/XML", str(xml), "/F"]]
        p.start = [["schtasks", "/Run", "/TN", TASK]]
        p.stop = [["schtasks", "/End", "/TN", TASK]]
        p.uninstall = [["schtasks", "/End", "/TN", TASK], ["schtasks", "/Delete", "/TN", TASK, "/F"]]
        p.status = ["schtasks", "/Query", "/TN", TASK]
        p.remove = [xml]
    elif platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        p.files[plist] = _launchd_plist(cmd, home)
        uid = str(os.getuid()) if hasattr(os, "getuid") else "0"
        p.install = [["launchctl", "bootstrap", f"gui/{uid}", str(plist)]]
        p.uninstall = [["launchctl", "bootout", f"gui/{uid}/{LABEL}"]]
        p.restart = [["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"]]
        p.status = ["launchctl", "print", f"gui/{uid}/{LABEL}"]
        p.remove = [plist]
    else:
        unit = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / "ronda.service"
        p.files[unit] = _systemd_unit(cmd)
        p.install = [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "ronda.service"]]
        p.uninstall = [["systemctl", "--user", "disable", "--now", "ronda.service"]]
        p.restart = [["systemctl", "--user", "restart", "ronda.service"]]
        p.status = ["systemctl", "--user", "is-active", "ronda.service"]
        p.remove = [unit]
    return p


def run(commands: list[list[str]], check: bool = True) -> list[subprocess.CompletedProcess]:
    out = []
    for c in commands:
        r = subprocess.run(c, capture_output=True, text=True)
        out.append(r)
        if check and r.returncode != 0:
            raise RuntimeError(f"{' '.join(c[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return out


def installed(p: Plan) -> bool:
    try:
        return subprocess.run(p.status, capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def port_busy(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def restart(p: Plan, busy, run_=run, wait_s: float = 20.0, clock=time.monotonic, sleep=time.sleep) -> bool:
    """Restart the service's hub. Task Scheduler's End returns before the hub has exited, and a hub
    started meanwhile finds the port busy and exits, so on Windows wait until the port is free.
    False when the old hub is still there after ``wait_s``: nothing is started then."""
    if not p.stop:
        run_(p.restart)
        return True
    run_(p.stop, check=False)
    end = clock() + wait_s
    while busy():
        if clock() >= end:
            return False
        sleep(0.25)
    run_(p.start)
    return True
