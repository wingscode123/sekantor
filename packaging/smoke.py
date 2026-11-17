"""Smoke test for the PyInstaller folder: `python packaging/smoke.py dist/sekantor [--port 7899] [--service]`.

Everything runs against a fresh temporary SEKANTOR_HOME and CLAUDE_CONFIG_DIR, so the real ~/.sekantor
and ~/.claude are never read or changed. It refuses the default port 7878 (a real hub may run there),
stops only the hub it started, and kills that hub's process tree if anything is left at the end.

Checks:
  1. `sekantor version` exits 0.
  2. `sekantor-hook` with a PreToolUse payload and no hub exits 0 in under 5 s and prints nothing.
  3. `sekantor-hub up --no-open --port P` answers GET /v1/health (token from the temp home) with 200
     within 30 s.
  4. `sekantor stop` exits 0 and the hub process ends.
  5. What the uninstaller runs (desktop/src-tauri/windows/hooks.nsh): `install claude --global` then
     `uninstall claude --global` leaves no SeKantor hook in the temp Claude settings.
  6. With --service only (CI, where the Task Scheduler is a throwaway VM's): `service install --no-start`
     then `service uninstall` leaves no login task. Never pass --service on a machine whose hub you use.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REAL_PORT = 7878
EXE = ".exe" if sys.platform == "win32" else ""


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        import psutil

        for child in psutil.Process(proc.pid).children(recursive=True):
            child.kill()
    except Exception:
        pass
    proc.kill()
    proc.wait(10)


class Smoke:
    def __init__(self, folder: Path, port: int, root: Path):
        self.folder, self.port, self.failures = folder, port, 0
        self.env = {**os.environ, "SEKANTOR_HOME": str(root / "home"), "SEKANTOR_PORT": str(port),
                    "CLAUDE_CONFIG_DIR": str(root / "claude")}
        self.env.pop("SEKANTOR_URL", None)
        self.home = Path(self.env["SEKANTOR_HOME"])

    def exe(self, stem: str) -> str:
        return str(self.folder / (stem + EXE))

    def check(self, ok: bool, what: str, detail: str = "") -> bool:
        print(("ok   " if ok else "FAIL ") + what + (f": {detail}" if detail and not ok else ""), flush=True)
        self.failures += not ok
        return ok

    def run(self, stem: str, *args: str, stdin: bytes | None = None, timeout: float = 60):
        return subprocess.run([self.exe(stem), *args], input=stdin, capture_output=True, env=self.env,
                              timeout=timeout)

    def version(self):
        r = self.run("sekantor", "version")
        self.check(r.returncode == 0, f"sekantor version -> {r.stdout.decode().strip()}", r.stderr.decode())

    def hook_without_hub(self):
        payload = {"session_id": "smoke-0001", "hook_event_name": "PreToolUse", "cwd": str(self.home),
                   "tool_name": "Bash", "tool_input": {"command": "echo hi"}, "transcript_path": ""}
        start = time.monotonic()
        r = self.run("sekantor-hook", stdin=json.dumps(payload).encode(), timeout=30)
        took = time.monotonic() - start
        self.check(r.returncode == 0 and took < 5 and not r.stdout,
                   f"sekantor-hook without a hub: exit {r.returncode}, {took:.1f} s, stdout {len(r.stdout)} bytes",
                   r.stderr.decode())

    def health(self) -> int:
        token_file = self.home / "token"
        if not token_file.is_file():
            return 0
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/health",
                                     headers={"Authorization": f"Bearer {token_file.read_text().strip()}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except OSError:
            return 0

    def hub_up_and_stop(self):
        flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {}
        hub = subprocess.Popen([self.exe("sekantor-hub"), "up", "--no-open", "--port", str(self.port)],
                               env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        try:
            start, status = time.monotonic(), 0
            while time.monotonic() - start < 30 and hub.poll() is None:
                status = self.health()
                if status == 200:
                    break
                time.sleep(0.5)
            took = time.monotonic() - start
            if not self.check(status == 200, f"sekantor-hub up: /v1/health {status} after {took:.1f} s",
                              f"hub exit code {hub.poll()}"):
                return
            r = self.run("sekantor", "stop")
            self.check(r.returncode == 0, f"sekantor stop -> {r.stdout.decode().strip()}", r.stderr.decode())
            try:
                hub.wait(20)
            except subprocess.TimeoutExpired:
                pass
            self.check(hub.poll() is not None and not port_open(self.port), "hub process gone after stop")
        finally:
            kill_tree(hub)

    def claude_hooks_round_trip(self):
        settings = Path(self.env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        r = self.run("sekantor", "install", "claude", "--global")
        text = settings.read_text(encoding="utf-8") if settings.is_file() else ""
        self.check(r.returncode == 0 and "sekantor-hook" in text, "install claude --global writes frozen hooks",
                   r.stdout.decode() + r.stderr.decode())
        r = self.run("sekantor", "uninstall", "claude", "--global")
        text = settings.read_text(encoding="utf-8") if settings.is_file() else ""
        self.check(r.returncode == 0 and "sekantor-hook" not in text, "uninstall claude --global leaves no hooks",
                   r.stdout.decode() + r.stderr.decode())

    def service_round_trip(self):
        r = self.run("sekantor", "service", "install", "--no-start")
        self.check(r.returncode == 0, "service install --no-start", r.stdout.decode() + r.stderr.decode())
        r = self.run("sekantor", "service", "uninstall")
        self.check(r.returncode == 0, "service uninstall", r.stdout.decode() + r.stderr.decode())
        if sys.platform == "win32":
            q = subprocess.run(["schtasks", "/Query", "/TN", "SeKantor hub"], capture_output=True)
            self.check(q.returncode != 0, "no login task left after service uninstall")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="the PyInstaller output, e.g. dist/sekantor")
    ap.add_argument("--port", type=int, default=7899)
    ap.add_argument("--service", action="store_true", help="also install and remove the login task (CI only)")
    args = ap.parse_args(argv)

    if args.port == REAL_PORT:
        sys.exit(f"refusing port {REAL_PORT}: that is where a real hub runs")
    if port_open(args.port):
        sys.exit(f"port {args.port} is already in use; pick another with --port")
    for stem in ("sekantor", "sekantor-hub", "sekantor-hook"):
        if not (args.folder / (stem + EXE)).is_file():
            sys.exit(f"missing {stem}{EXE} in {args.folder}")

    root = Path(tempfile.mkdtemp(prefix="sekantor-smoke-"))
    smoke = Smoke(args.folder.resolve(), args.port, root)
    print(f"SEKANTOR_HOME={smoke.home} port={args.port}", flush=True)
    try:
        smoke.version()
        smoke.hook_without_hub()
        smoke.hub_up_and_stop()
        smoke.claude_hooks_round_trip()
        if args.service:
            smoke.service_round_trip()
    finally:
        logs = Path(os.environ.get("SMOKE_LOG_DIR", ""))
        if os.environ.get("SMOKE_LOG_DIR") and smoke.home.is_dir():
            shutil.copytree(smoke.home, logs / "sekantor-home", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("token"))
        shutil.rmtree(root, ignore_errors=True)
    print(f"{smoke.failures} failure(s)" if smoke.failures else "smoke passed", flush=True)
    return 1 if smoke.failures else 0


if __name__ == "__main__":
    sys.exit(main())
