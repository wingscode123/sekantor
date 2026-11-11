"""``ronda-hook``: the Claude Code command hook (read-only in M1).

Reads the hook payload on stdin, turns it into a Ronda event, adds the host fingerprint and the
agent PID, and POSTs it to the hub. Whatever happens it prints nothing and exits 0: "no decision",
so Claude Code behaves exactly as without Ronda (fail closed, ADR-0003). A watchdog ends the process
after 2 s even if something hangs.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request

HARD_TIMEOUT_S = 2.0
HTTP_TIMEOUT_S = 1.0  # Windows takes ~2 s to refuse a closed loopback port; stay under the watchdog
SESSION_END_HTTP_TIMEOUT_S = 0.5  # SessionEnd hooks share a 1.5 s budget
MAX_STDIN = 4 * 1024 * 1024
LOG_MAX = 256 * 1024


def _home() -> str:
    return os.environ.get("RONDA_HOME") or os.path.join(os.path.expanduser("~"), ".ronda")


def _log(message: str) -> None:
    try:
        path = os.path.join(_home(), "hook.log")
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    except OSError:
        pass


def _hub_url() -> str:
    port = os.environ.get("RONDA_PORT", "7878")
    return os.environ.get("RONDA_URL") or f"http://127.0.0.1:{port}"


def _token() -> str | None:
    try:
        with open(os.path.join(_home(), "token"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def build_event(payload: dict, env: dict[str, str]) -> dict | None:
    from ronda.pos.claude_code.translate import translate

    event = translate(payload)
    if event is None:
        return None
    try:
        pid = int(env.get("CLAUDE_PID", ""))
    except ValueError:
        pid = None
    if pid and pid > 0:
        event["process"] = {"pid": pid}
    try:
        from ronda.pos.claude_code.fingerprint import classify, collect, load_rules

        deep = payload.get("hook_event_name") == "SessionStart"
        chain, exe, cmdline = collect(env, payload.get("cwd"), pid, deep)
        host = classify(load_rules(), env, chain, exe, payload.get("cwd"), cmdline)
        if host:
            event["host"] = host
    except Exception as e:  # a broken rules file must not lose the event
        _log(f"fingerprint failed: {type(e).__name__}: {e}")
    return event


def post(event: dict, timeout: float) -> None:
    token = _token()
    if not token:
        _log("no token: run `ronda up` once")
        return
    req = urllib.request.Request(
        _hub_url() + "/v1/events",
        data=json.dumps(event).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def run(stdin: bytes, env: dict[str, str]) -> None:
    payload = json.loads(stdin.decode("utf-8"))
    if not isinstance(payload, dict):
        return
    event = build_event(payload, env)
    if event is None:
        return
    timeout = SESSION_END_HTTP_TIMEOUT_S if event.get("type") == "session_ended" else HTTP_TIMEOUT_S
    try:
        post(event, timeout)
    except Exception as e:
        _log(f"{payload.get('hook_event_name')}: hub unreachable ({type(e).__name__})")


def main() -> None:
    watchdog = threading.Timer(HARD_TIMEOUT_S, lambda: os._exit(0))
    watchdog.daemon = True
    watchdog.start()
    try:
        run(sys.stdin.buffer.read(MAX_STDIN), dict(os.environ))
    except Exception as e:
        _log(f"hook error: {type(e).__name__}: {e}")
    finally:
        sys.stdout.flush()
        os._exit(0)  # always "no decision"


if __name__ == "__main__":
    main()
