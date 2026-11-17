"""Smoke test for the PyInstaller folder: `python packaging/smoke.py dist/sekantor [--port 7899] [--service]`.

Everything runs against a fresh temporary SEKANTOR_HOME and CLAUDE_CONFIG_DIR, so the real ~/.sekantor
and ~/.claude are never read or changed. It refuses the default port 7878 (a real hub may run there),
stops only the hub it started, and kills that hub's process tree if anything is left at the end.

The folder holds the PyInstaller exes and, in CI, the native `sekantor-hook.exe` (hook/, ADR-0026)
copied in after PyInstaller. Without it (a local build has no Rust toolchain) the hook checks are
skipped with a message; CI always has it.

Checks:
  1. `sekantor version` exits 0.
  2. `sekantor-hub up --no-open --port P` answers GET /v1/health (token from the temp home) with 200
     within 30 s.
  3. Native hook, with that hub up: a PreToolUse `Bash` payload is stored as an event with
     `activity.kind == "run"` (read back from GET /v1/sessions/{id}/events), and a payload whose cwd
     matches `ignore_cwd` (OpenBot's program folder) adds no sent.log line.
  4. `sekantor stop --wait` exits 0 and the hub process has ended by then.
  5. Native hook, hub stopped: exits 0 in under 3 s, prints nothing and adds exactly one hook.log line,
     "hub unreachable (<kind>) <event id>" as `sekantor stats` reads it.
  6. What the uninstaller runs (desktop/src-tauri/windows/hooks.nsh): `install claude --global` then
     `uninstall claude --global` leaves no SeKantor hook in the temp Claude settings (needs the hook).
  7. With --service only, and only when CIRCLECI is set (a throwaway VM): `service install --no-start`
     then `service uninstall` leaves no login task. It refuses to run elsewhere.
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
import urllib.parse
import urllib.request
from pathlib import Path

from sekantor.stats import UNREACHABLE_ID

REAL_PORT = 7878
EXE = ".exe" if sys.platform == "win32" else ""
HOOK = "sekantor-hook"
OPENBOT_CWD = "C:/Users/smoke/AppData/Local/Programs/OpenBot/resources/app"  # matches DEFAULT_IGNORE_CWD


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []


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
        self.native_hook = (folder / (HOOK + EXE)).is_file()

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

    def skip_without_hook(self, what: str) -> bool:
        if not self.native_hook:
            print(f"skip {what}: no {HOOK}{EXE} in the folder (built by cargo in CI only)", flush=True)
        return not self.native_hook

    def hook(self, session: str, cwd: str) -> tuple[subprocess.CompletedProcess, float]:
        payload = {"session_id": session, "hook_event_name": "PreToolUse", "cwd": cwd, "tool_name": "Bash",
                   "tool_input": {"command": "echo hi"}, "transcript_path": ""}
        start = time.monotonic()
        r = self.run(HOOK, stdin=json.dumps(payload).encode(), timeout=30)
        return r, time.monotonic() - start

    def get(self, path: str) -> tuple[int, dict]:
        token_file = self.home / "token"
        if not token_file.is_file():
            return 0, {}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     headers={"Authorization": f"Bearer {token_file.read_text().strip()}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (OSError, ValueError):
            return 0, {}

    def health(self) -> int:
        return self.get("/v1/health")[0]

    def hook_with_hub(self):
        if self.skip_without_hook("hook with a hub"):
            return
        session = "smoke-run-0001"
        r, took = self.hook(session, str(self.home))
        self.check(r.returncode == 0 and not r.stdout,
                   f"{HOOK} with a hub: exit {r.returncode}, {took:.1f} s, stdout {len(r.stdout)} bytes",
                   r.stderr.decode())
        path = f"/v1/sessions/{urllib.parse.quote('claude:' + session, safe='')}/events"
        kinds, end = [], time.monotonic() + 5
        while time.monotonic() < end:
            kinds = [(e.get("activity") or {}).get("kind") for e in self.get(path)[1].get("events", [])]
            if "run" in kinds:
                break
            time.sleep(0.25)
        self.check("run" in kinds, "PreToolUse Bash stored with activity.kind run",
                   f"activity kinds {kinds}; hook.log: {lines(self.home / 'hook.log')[-3:]}")

        sent_before = len(lines(self.home / "sent.log"))
        r, took = self.hook("smoke-openbot-0001", OPENBOT_CWD)
        added = len(lines(self.home / "sent.log")) - sent_before
        self.check(r.returncode == 0 and not r.stdout and added == 0,
                   f"{HOOK} with an ignore_cwd payload: exit {r.returncode}, sent.log +{added}", r.stderr.decode())

    def hook_without_hub(self):
        if self.skip_without_hook("hook without a hub"):
            return
        log = self.home / "hook.log"
        before = lines(log)
        r, took = self.hook("smoke-nohub-0001", str(self.home))
        new = lines(log)[len(before):]
        self.check(r.returncode == 0 and took < 3 and not r.stdout,
                   f"{HOOK} without a hub: exit {r.returncode}, {took:.1f} s, stdout {len(r.stdout)} bytes",
                   r.stderr.decode())
        self.check(len(new) == 1 and UNREACHABLE_ID.search(new[0]) is not None,
                   'one hook.log line "hub unreachable (<kind>) <id>"', f"new hook.log lines {new}")

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
            self.hook_with_hub()
            r = self.run("sekantor", "stop", "--wait")
            self.check(r.returncode == 0, f"sekantor stop --wait -> {r.stdout.decode().strip()}", r.stderr.decode())
            # --wait returned: the hub process must already be gone (the uninstaller deletes its files next).
            try:
                hub.wait(1)
            except subprocess.TimeoutExpired:
                pass
            self.check(hub.poll() is not None and not port_open(self.port), "hub process gone when stop --wait returns")
        finally:
            kill_tree(hub)

    def claude_hooks_round_trip(self):
        if self.skip_without_hook("install/uninstall claude --global"):
            return
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

    if args.service and not os.environ.get("CIRCLECI"):
        sys.exit("--service changes this machine's \"SeKantor hub\" login task: CI only (CIRCLECI is not set)")
    if args.port == REAL_PORT:
        sys.exit(f"refusing port {REAL_PORT}: that is where a real hub runs")
    if port_open(args.port):
        sys.exit(f"port {args.port} is already in use; pick another with --port")
    for stem in ("sekantor", "sekantor-hub"):
        if not (args.folder / (stem + EXE)).is_file():
            sys.exit(f"missing {stem}{EXE} in {args.folder}")

    root = Path(tempfile.mkdtemp(prefix="sekantor-smoke-"))
    smoke = Smoke(args.folder.resolve(), args.port, root)
    print(f"SEKANTOR_HOME={smoke.home} port={args.port}", flush=True)
    try:
        smoke.version()
        smoke.hub_up_and_stop()
        smoke.hook_without_hub()  # after the hub ran: its token is in the temp home and the port is free
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
