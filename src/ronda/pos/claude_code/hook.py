"""``ronda-hook``: the Claude Code command hook.

Reads the hook payload on stdin, turns it into a Ronda event, adds the host fingerprint and the agent
PID, and POSTs it to the hub. Two events then wait for an answer from Ronda (ADR-0008):

- PermissionRequest (runs synchronously): long-polls the hub for an approve/deny for this exact
  request, up to ``approval_wait``. The terminal or host prompt stays usable meanwhile; whoever
  answers first wins. Only an explicit action prints a decision.
- Stop (runs async with asyncRewake): long-polls for a reply, up to ``reply_wait``. A reply exits 2
  with the text on stderr, which wakes the agent.

Everything else, and every failure (hub down, timeout, bad input, crash), prints nothing and exits 0:
"no decision", so Claude Code behaves exactly as without Ronda (fail closed). A watchdog ends the
process at its deadline even if something hangs.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone

HARD_TIMEOUT_S = 2.0
HTTP_TIMEOUT_S = 1.0  # Windows takes ~2 s to refuse a closed loopback port; stay under the watchdog
SESSION_END_HTTP_TIMEOUT_S = 1.5  # install raises SessionEnd's budget to 5 s (default 1.5 s)
POLL_S = 25.0  # one long-poll request; the hub caps it at 30 s
MAX_STDIN = 4 * 1024 * 1024
LOG_MAX = 256 * 1024
SENT_MAX = 2 * 1024 * 1024
REPLY_PREFIX = "Reply from the user, sent through Ronda:\n"


# --- plumbing ---------------------------------------------------------------------

class Watchdog:
    """Ends the process with "no decision" at the deadline; the deadline can be pushed out once we know
    the hook is meant to wait."""

    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds
        threading.Thread(target=self._run, daemon=True).start()

    def extend_to(self, seconds_from_now: float) -> None:
        self.deadline = max(self.deadline, time.monotonic() + seconds_from_now)

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def _run(self) -> None:
        while True:
            left = self.deadline - time.monotonic()
            if left <= 0:
                os._exit(0)
            time.sleep(min(left, 0.5))


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


def _hub_addr() -> tuple[str, int]:
    url = _hub_url().split("://", 1)[-1].split("/", 1)[0]
    host, _, port = url.rpartition(":")
    return (host or url), int(port or 80)


def _token() -> str | None:
    try:
        with open(os.path.join(_home(), "token"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _settings():
    from pathlib import Path

    from ronda.config import settings

    return settings(Path(_home()))


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


def _host(payload: dict, env: dict[str, str], deep: bool) -> dict | None:
    try:
        from ronda.pos.claude_code.fingerprint import classify, collect, load_rules

        chain, exe, cmdline = collect(env, payload.get("cwd"), _pid(env), deep)
        return classify(load_rules(), env, chain, exe, payload.get("cwd"), cmdline)
    except Exception as e:  # a broken rules file must not lose the event
        _log(f"fingerprint failed: {type(e).__name__}: {e}")
        return None


def capabilities(payload: dict, env: dict[str, str], settings) -> list[str]:
    """What Ronda may do for this request (FR-25). Reply only where it was verified (ADR-0008)."""
    name = payload.get("hook_event_name")
    if name == "PermissionRequest" and payload.get("tool_name") == "AskUserQuestion":
        return []  # a question to answer in the app; approving would not answer it
    if name == "PermissionRequest" and settings.approval_wait_s > 0:
        return ["approve", "deny"]
    if name == "Stop" and settings.reply_wait_s > 0 and env.get("CLAUDE_CODE_ENTRYPOINT") in settings.reply_entrypoints:
        return ["reply"]
    return []


def build_event(payload: dict, env: dict[str, str], deep: bool = False, settings=None) -> dict | None:
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
    if settings is not None:
        caps = capabilities(payload, env, settings)
        if caps:
            event["capabilities"] = caps
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


def post(event: dict, timeout: float) -> None:
    token = _token()
    if not token:
        _log("no token: run `ronda up` once")
        raise RuntimeError("no token")
    _record_sent(event)
    status, _ = request("POST", "/v1/events", token, event, timeout)
    if not 200 <= status < 300:
        raise RuntimeError(f"hub answered {status}")


# --- waiting for an answer (ADR-0008) --------------------------------------------------

def wait_for_action(event: dict, kind: str, watchdog: Watchdog) -> dict | None:
    """Long-poll the hub until an action arrives, the request is resolved elsewhere, or time is up."""
    from urllib.parse import quote

    token = _token()
    if not token:
        return None
    path = (f"/v1/sessions/{quote(event['session_id'], safe='')}/actions/next"
            f"?for={kind}&request_id={quote(event['request']['id'], safe='')}")
    while True:
        left = watchdog.remaining() - 2.0
        if left <= 0.5:
            return None
        wait = min(POLL_S, left)
        status, body = request("GET", f"{path}&wait={wait:.1f}", token, None, timeout=wait + 5)
        if status != 200:
            return None
        result = json.loads(body)
        if result.get("action"):
            return result["action"]
        if result.get("reason") != "timeout":
            return None  # answered in the terminal, session moved on, or ended


def decision(action: dict) -> dict | None:
    if action.get("type") == "approve":
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    if action.get("type") == "deny":
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {
            "behavior": "deny", "message": "Denied by the user from Ronda."}}}
    return None


def run(stdin: bytes, env: dict[str, str], watchdog: Watchdog, can_wait: bool = False) -> int:
    """Returns the exit code: 0, or 2 only to deliver a reply on Stop.

    ``can_wait`` comes from the ``--wait`` argument, which only an install that runs PermissionRequest
    synchronously and Stop with asyncRewake passes. An older install never waits and never offers
    approve or reply, so it cannot swallow an answer it has no way to deliver."""
    payload = json.loads(stdin.decode("utf-8"))
    if not isinstance(payload, dict):
        return 0
    settings = _settings()
    if settings.ignored(payload.get("cwd")):
        return 0  # e.g. OpenBot's own helper runs from its program folder
    event = build_event(payload, env, settings=settings if can_wait else None)  # env-only fingerprint: fast
    if event is None:
        return 0
    timeout = SESSION_END_HTTP_TIMEOUT_S if event.get("type") == "session_ended" else HTTP_TIMEOUT_S
    name = payload.get("hook_event_name")
    try:
        post(event, timeout)
        if event.get("type") == "session_started":
            update = host_update(event, payload, env)
            if update:
                post(update, timeout)
    except Exception as e:
        _log(f"{name}: hub unreachable ({type(e).__name__})")
        return 0

    caps = event.get("capabilities") or []
    try:
        if name == "PermissionRequest" and "approve" in caps:
            watchdog.extend_to(settings.approval_wait_s)
            action = wait_for_action(event, "approval", watchdog)
            out = decision(action) if action else None
            if out:
                sys.stdout.write(json.dumps(out))
            return 0
        if name == "Stop" and "reply" in caps:
            watchdog.extend_to(settings.reply_wait_s)
            action = wait_for_action(event, "reply", watchdog)
            text = (action or {}).get("text")
            if action and action.get("type") == "reply" and text:
                sys.stderr.buffer.write((REPLY_PREFIX + text).encode("utf-8"))
                return 2
    except Exception as e:
        _log(f"{name}: waiting for Ronda failed ({type(e).__name__})")
    return 0


def main() -> None:
    watchdog = Watchdog(HARD_TIMEOUT_S)
    code = 0
    try:
        code = run(sys.stdin.buffer.read(MAX_STDIN), dict(os.environ), watchdog, can_wait="--wait" in sys.argv[1:])
    except Exception as e:
        _log(f"hook error: {type(e).__name__}: {e}")
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code if code in (0, 2) else 0)


if __name__ == "__main__":
    main()
