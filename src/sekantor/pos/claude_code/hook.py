"""``sekantor-hook``: the Claude Code command hook.

Reads the hook payload on stdin, turns it into a SeKantor event, adds the host fingerprint and the agent
PID, and POSTs it to the hub. That is all it does (ADR-0021): SeKantor watches and never answers, so every
hook runs asynchronously and prints nothing, except SessionEnd: it runs synchronously (short timeout)
so the event still goes out while Claude Code exits.

Every failure (hub down, timeout, bad input, crash) prints nothing and exits 0, so Claude Code behaves
exactly as without SeKantor (fail closed). A watchdog ends the process at its deadline even if something
hangs.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone

from sekantor import config

HARD_TIMEOUT_S = 2.0
HTTP_TIMEOUT_S = 1.0  # Windows takes ~2 s to refuse a closed loopback port; stay under the watchdog
SESSION_END_HTTP_TIMEOUT_S = 1.5  # SessionEnd is the one synchronous hook (5 s timeout), so it may wait a little longer
MAX_STDIN = 4 * 1024 * 1024
LOG_MAX = 256 * 1024
SENT_MAX = 2 * 1024 * 1024


# --- plumbing ---------------------------------------------------------------------

class Watchdog:
    """Ends the process at the deadline, whatever the hook is stuck on."""

    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            left = self.deadline - time.monotonic()
            if left <= 0:
                os._exit(0)
            time.sleep(min(left, 0.5))


def _log(message: str) -> None:
    try:
        path = str(config.hook_log_path())
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    except OSError:
        pass


def _record_sent(event: dict) -> None:
    """One line per event the hook tries to deliver; `sekantor stats` compares it with what the hub stored."""
    try:
        path = str(config.home() / "sent.log")
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


def _hub_addr() -> tuple[str, int]:
    url = config.hub_url().split("://", 1)[-1].split("/", 1)[0]
    host, _, port = url.rpartition(":")
    return (host or url), int(port or 80)


def _token() -> str | None:
    try:
        with open(config.token_path(), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _settings():
    return config.settings()


def request(method: str, path: str, token: str, body: dict | None, timeout: float) -> tuple[int, bytes]:
    """HTTP/1.1 to the loopback hub over a plain socket: urllib pulls in http.client and email (slow imports)."""
    host, port = _hub_addr()
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}:{port}", f"Authorization: Bearer {token}",
             "Connection: close"]
    if body is not None:
        lines += ["Content-Type: application/json", f"Content-Length: {len(data)}"]
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    chunks = []
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(head + data)
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    status_line, _, rest = raw.partition(b"\r\n")
    try:
        status = int(status_line.split(b" ", 2)[1])
    except (IndexError, ValueError):
        raise RuntimeError("bad response from hub") from None
    headers, _, payload = rest.partition(b"\r\n\r\n")
    if b"transfer-encoding: chunked" in headers.lower():
        payload = _dechunk(payload)
    return status, payload


def _dechunk(data: bytes) -> bytes:
    out, i = [], 0
    while i < len(data):
        j = data.index(b"\r\n", i)
        size = int(data[i:j].split(b";")[0], 16)
        if size == 0:
            break
        out.append(data[j + 2:j + 2 + size])
        i = j + 2 + size + 2
    return b"".join(out)


# --- events -------------------------------------------------------------------------

def _pid(env: dict[str, str]) -> int | None:
    try:
        pid = int(env.get("CLAUDE_PID", ""))
    except ValueError:
        return None
    return pid if pid > 0 else None


def _host(payload: dict, env: dict[str, str], deep: bool, from_agent: bool = False) -> dict | None:
    """``from_agent``: the hub is asking, so the parent chain starts at the agent, not at this process."""
    try:
        from sekantor.pos.claude_code.fingerprint import classify, collect, load_rules

        chain, exe, cmdline = collect(_pid(env), deep, from_agent=True) if from_agent else collect(_pid(env), deep)
        return classify(load_rules(), env, chain, exe, payload.get("cwd"), cmdline)
    except Exception as e:  # a broken rules file must not lose the event
        _log(f"fingerprint failed: {type(e).__name__}: {e}")
        return None


def build_event(payload: dict, env: dict[str, str], event_id: str | None = None, ts: str | None = None) -> dict | None:
    """The SeKantor event for a hook payload. The hub passes the forwarder's own ``event_id`` and ``ts``."""
    from sekantor.pos.claude_code.translate import translate

    event = translate(payload)
    if event is None:
        return None
    if event_id:
        event["event_id"] = event_id
    if ts:
        event["ts"] = ts
    pid = _pid(env)
    if pid:
        event["process"] = {"pid": pid}
    from sekantor.pos.claude_code.fingerprint import _env_get

    for field, name in (("orca_session_id", "ORCA_AGENT_SESSION_ID"), ("orca_terminal_handle", "ORCA_TERMINAL_HANDLE")):
        if value := _env_get(env, name):
            event[field] = value
    host = _host(payload, env, deep=False)
    if host:
        event["host"] = host
    return event


def host_update(event: dict, payload: dict, env: dict[str, str], from_agent: bool = False) -> dict | None:
    """After SessionStart: the parent chain and agent exe (slow on Windows) as a follow-up event."""
    from sekantor.pos.claude_code.translate import new_event_id

    host = _host(payload, env, deep=True, from_agent=from_agent)
    if not host or (event.get("host") and host["confidence"] <= event["host"]["confidence"]):
        return None
    return {k: event[k] for k in ("v", "source", "session_id", "agent", "workspace") if k in event} | {
        "event_id": new_event_id(), "ts": datetime.now(timezone.utc).isoformat(),
        "type": "message", "host": host,
    }


def post(event: dict, timeout: float) -> None:
    token = _token()
    if not token:
        _log("no token: run `sekantor up` once")
        raise RuntimeError("no token")
    _record_sent(event)
    status, _ = request("POST", "/v1/events", token, event, timeout)
    if not 200 <= status < 300:
        raise RuntimeError(f"hub answered {status}")


def run(stdin: bytes, env: dict[str, str], watchdog: Watchdog) -> int:
    """Send the event and return 0 (always: a hook never changes what the agent does)."""
    payload = json.loads(stdin.decode("utf-8"))
    if not isinstance(payload, dict):
        return 0
    if _settings().ignored(payload.get("cwd")):
        return 0  # e.g. OpenBot's own helper runs from its program folder
    event = build_event(payload, env)  # env-only fingerprint: fast
    if event is None:
        return 0
    timeout = SESSION_END_HTTP_TIMEOUT_S if event.get("type") == "session_ended" else HTTP_TIMEOUT_S
    sending = event
    try:
        post(event, timeout)
        if event.get("type") == "session_started":
            sending = host_update(event, payload, env)
            if sending:
                post(sending, timeout)
    except Exception as e:
        # The event id lets `sekantor stats` match this line to the event, however late it is logged.
        _log(f"{payload.get('hook_event_name')}: hub unreachable ({type(e).__name__}) {(sending or event)['event_id']}")
    return 0


def main() -> None:
    watchdog = Watchdog(HARD_TIMEOUT_S)
    try:
        run(sys.stdin.buffer.read(MAX_STDIN), dict(os.environ), watchdog)
    except Exception as e:
        _log(f"hook error: {type(e).__name__}: {e}")
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
