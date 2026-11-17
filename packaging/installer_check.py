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
from pathlib import Path

TASK = "SeKantor hub"


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
    check(str(inst).lower().replace("\\", "/") in settings.read_text(encoding="utf-8").lower().replace("\\\\", "/"),
          "hooks point at the installed sekantor-hook.exe")

    # `_?=` makes the uninstaller run in place and wait, instead of copying itself to TEMP and returning.
    r = subprocess.run([str(inst / "uninstall.exe"), "/S", f"_?={inst}"], timeout=300)
    check(r.returncode == 0, f"silent uninstall exit {r.returncode}")
    time.sleep(2)
    text = settings.read_text(encoding="utf-8") if settings.is_file() else ""
    check("sekantor-hook" not in text, "no SeKantor hooks left in ~/.claude/settings.json", text[:500])
    q = subprocess.run(["schtasks", "/Query", "/TN", TASK], capture_output=True)
    check(q.returncode != 0, "no login task left")
    check(not cli.exists(), "sekantor folder removed")
    print(f"{failures} failure(s)" if failures else "installer check passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
