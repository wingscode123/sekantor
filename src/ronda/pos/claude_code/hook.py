"""``ronda-hook``: the Claude Code command hook (read-only in M1).

Reads the hook payload on stdin, turns it into a Ronda event, adds the host fingerprint and the
agent PID, and POSTs it to the hub. Whatever happens it prints nothing and exits 0: "no decision",
so Claude Code behaves exactly as without Ronda (fail closed, ADR-0003). A watchdog ends the process
after 2 s even if something hangs.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import sys
import threading
import socket
import time

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


SENT_MAX = 2 * 1024 * 1024


def _record_sent(event: dict) -> None:
    """One line per event the hook tries to deliver; `ronda stats` compares it with what the hub stored."""
    try:
        path = os.path.join(_home(), "sent.log")
        if os.path.exists(path) and os.path.getsize(path) > SENT_MAX:
            os.replace(path, path + ".1")
        line = f"{event.get('ts')} {event.get('event_id')} {event.get('session_id')} {event.get('status') or event.get('type')}\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))  # one write per line: safe with hooks running in parallel
        finally:
            os.close(fd)
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


def _pid(env: dict[str, str]) -> int | None:
    try:
        pid = int(env.get("CLAUDE_PID", ""))
    except ValueError:
        return None
    return pid if pid > 0 else None


def _host(payload: dict, env: dict[str, str], deep: bool) -> dict | None:
    try:
        from ronda.pos.claude_code.fingerprint import classify, collect, load_rules

        chain, exe, cmdline = collect(env, payload.get("cwd"), _pid(env), deep)
        return classify(load_rules(), env, chain, exe, payload.get("cwd"), cmdline)
    except Exception as e:  # a broken rules file must not lose the event
        _log(f"fingerprint failed: {type(e).__name__}: {e}")
        return None


def build_event(payload: dict, env: dict[str, str], deep: bool = False) -> dict | None:
    from ronda.pos.claude_code.translate import translate

    event = translate(payload)
    if event is None:
        return None
    pid = _pid(env)
    if pid:
        event["process"] = {"pid": pid}
    host = _host(payload, env, deep)
    if host:
        event["host"] = host
    return event


def host_update(event: dict, payload: dict, env: dict[str, str]) -> dict | None:
    """After SessionStart: the parent chain and agent exe (slow on Windows) as a follow-up event."""
    from ronda.pos.claude_code.translate import new_event_id

    host = _host(payload, env, deep=True)
    if not host or (event.get("host") and host["confidence"] <= event["host"]["confidence"]):
        return None
    return {k: event[k] for k in ("v", "source", "session_id", "agent", "workspace") if k in event} | {
        "event_id": new_event_id(), "ts": datetime.now(timezone.utc).isoformat(),
        "type": "message", "host": host,
    }


def _hub_addr() -> tuple[str, int]:
    url = _hub_url().split("://", 1)[-1].split("/", 1)[0]
    host, _, port = url.rpartition(":")
    return (host or url), int(port or 80)


def post(event: dict, timeout: float) -> None:
    """POST to the loopback hub over a plain socket: urllib pulls in http.client and email (slow imports)."""
    token = _token()
    if not token:
        _log("no token: run `ronda up` once")
        return
    _record_sent(event)
    host, port = _hub_addr()
    body = json.dumps(event).encode("utf-8")
    lines = [
        "POST /v1/events HTTP/1.1",
        f"Host: {host}:{port}",
        f"Authorization: Bearer {token}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "",
        "",
    ]
    head = "\r\n".join(lines).encode("ascii")
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(head + body)
        status = sock.recv(32)
    if not status.startswith(b"HTTP/1.1 2"):
        raise RuntimeError(status.split(b"\r\n", 1)[0].decode("latin-1", "replace"))


def run(stdin: bytes, env: dict[str, str]) -> None:
    payload = json.loads(stdin.decode("utf-8"))
    if not isinstance(payload, dict):
        return
    event = build_event(payload, env)  # env-only fingerprint: fast, so the card shows at once
    if event is None:
        return
    timeout = SESSION_END_HTTP_TIMEOUT_S if event.get("type") == "session_ended" else HTTP_TIMEOUT_S
    try:
        post(event, timeout)
        if event.get("type") == "session_started":
            update = host_update(event, payload, env)
            if update:
                post(update, timeout)
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
