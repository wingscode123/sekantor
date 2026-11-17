"""CI only: install the NSIS setup silently, run first run, uninstall, and check nothing is left behind.

    python packaging/installer_check.py desktop/src-tauri/target/release/bundle/nsis/SeKantor_*-setup.exe

This uses the real home, ~/.claude/settings.json and the Task Scheduler of the machine it runs on, so it
refuses to run unless CIRCLECI is set (a throwaway VM). It covers Review Focus 5: the uninstaller's
pre-uninstall hook (desktop/src-tauri/windows/hooks.nsh) removes the hooks and the login task.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TASK = "SeKantor hub"
PORT = 7878  # the installed app's default; this runs only on a CI VM


def healthy() -> bool:
    token = Path.home() / ".sekantor" / "token"
    if not token.is_file():
        return False
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/health",
                                 headers={"Authorization": f"Bearer {token.read_text().strip()}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def wait_healthy(seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if healthy():
            return True
        time.sleep(0.5)
    return False


def hub_processes() -> list:
    import psutil

    return [p for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").lower() == "sekantor-hub.exe"]


def main(argv: list[str]) -> int:
    if not os.environ.get("CIRCLECI"):
        sys.exit("installer_check.py changes the real home and login tasks: CI only (CIRCLECI is not set)")
    setups = sorted(glob.glob(argv[0])) if argv else []
    if len(setups) != 1:
        sys.exit(f"expected one setup exe, found {setups}")
    failures = 0

    def check(ok: bool, what: str, detail: str = "") -> None:
        nonlocal failures
        print(("ok   " if ok else "FAIL ") + what + (f": {detail}" if detail and not ok else ""), flush=True)
        failures += not ok

    r = subprocess.run([setups[0], "/S"], timeout=300)
    inst = Path(os.environ["LOCALAPPDATA"]) / "SeKantor"
    cli = inst / "sekantor" / "sekantor.exe"
    check(r.returncode == 0, f"silent install exit {r.returncode}")
    for path in (inst / "SeKantor.exe", cli, inst / "sekantor" / "sekantor-hub.exe",
                 inst / "sekantor" / "sekantor-hook.exe", inst / "uninstall.exe"):
        check(path.is_file(), f"installed {path}")
    if failures:
        return 1

    # What the app's first run does ("Connect Claude Code").
    r = subprocess.run([str(cli), "setup", "--apply"], capture_output=True, text=True, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    report = json.loads(lines[-1]) if lines else {}
    check(r.returncode == 0 and report.get("hooks") == "ok" and report.get("service") is True,
          f"setup --apply -> {report}", r.stdout + r.stderr)
    settings = Path.home() / ".claude" / "settings.json"
    text = settings.read_text(encoding="utf-8") if settings.is_file() else ""
    # The native forwarder (hook/, ADR-0026) that CI copied into dist/sekantor/ before `tauri build`.
    hook = os.path.normcase((inst / "sekantor" / "sekantor-hook.exe").resolve())  # resolve: 8.3 short names
    commands = {os.path.normcase(Path(str(h.get("command", ""))).resolve())
                for groups in (json.loads(text).get("hooks", {}) if text else {}).values()
                for group in groups for h in group.get("hooks", [])
                if "sekantor-hook" in str(h.get("command", ""))}
    check(commands == {hook}, "hooks point at the installed sekantor-hook.exe",
          f"{settings} missing" if not text else f"commands {sorted(commands)}")
    r = subprocess.run([str(inst / "sekantor" / "sekantor-hook.exe")], input=b"", capture_output=True,
                       timeout=10)
    check(r.returncode == 0 and not r.stdout and not r.stderr, "installed sekantor-hook.exe exits 0 silently",
          f"exit {r.returncode}, stdout {r.stdout[:200]!r}, stderr {r.stderr[:200]!r}")

    # The uninstaller must cope with a running hub (its files are locked while it runs). The login task
    # was started by --apply; if Task Scheduler did not start it here, start the hub the way the app does.
    if not wait_healthy(20):
        print("login task did not start a hub; starting sekantor-hub.exe", flush=True)
        subprocess.Popen([str(inst / "sekantor" / "sekantor-hub.exe"), "up", "--no-open"],
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
    check(wait_healthy(30), "a hub is running before uninstall")

    # `_?=` makes the uninstaller run in place and wait, instead of copying itself to TEMP and returning.
    r = subprocess.run([str(inst / "uninstall.exe"), "/S", f"_?={inst}"], timeout=300)
    check(r.returncode == 0, f"silent uninstall exit {r.returncode}")
    time.sleep(2)
    text = settings.read_text(encoding="utf-8") if settings.is_file() else ""
    check("sekantor-hook" not in text, "no SeKantor hooks left in ~/.claude/settings.json", text[:500])
    q = subprocess.run(["schtasks", "/Query", "/TN", TASK], capture_output=True)
    check(q.returncode != 0, "no login task left")
    check(not (inst / "sekantor").exists(), "sekantor folder removed entirely",
          "\n".join(str(p) for p in (inst / "sekantor").rglob("*"))[:2000] if (inst / "sekantor").exists() else "")
    left = hub_processes()
    check(not left, "no sekantor-hub.exe process left", str([p.pid for p in left]))
    for p in left:
        p.kill()
    print(f"{failures} failure(s)" if failures else "installer check passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
