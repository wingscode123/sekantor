"""Local token auth for every request (HTTP, static files and WebSocket).

- The token lives in ~/.sekantor/token, mode 600, created on first use.
- Pos and the CLI send ``Authorization: Bearer <token>``.
- The browser opens ``/?login=<code>`` once (printed by ``sekantor up`` or ``sekantor open``): a one-time code,
  valid 10 minutes, so the token itself never appears in a URL or browser history. The hub sets an
  HttpOnly, SameSite=Strict cookie and redirects to ``/``. Cookie requests that change state or open a
  WebSocket must come from the hub's own origin.
- The Host header must name the loopback address (DNS rebinding guard).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

COOKIE = "sekantor_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def ensure_token(path: Path) -> str:
    """Return the token, creating it (mode 600) if missing. Tightens loose permissions on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if sys.platform != "win32" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            os.chmod(path, 0o600)
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    return token


def read_token(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def token_mode_ok(path: Path) -> bool:
    """True when only the owner can read the token (always True on Windows, where ACLs apply)."""
    if sys.platform == "win32":
        return path.exists()
    return path.exists() and stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def rotate_token(path: Path) -> str:
    """Replace the token (mode 600). Running hubs keep the old one until restarted."""
    if path.exists():
        path.unlink()
    return ensure_token(path)


class LoginCodes:
    """One-time codes for the browser login link, kept in memory only."""

    TTL_S = 600.0

    def __init__(self) -> None:
        self._codes: dict[str, float] = {}

    def _purge(self) -> None:
        now = time.monotonic()
        self._codes = {c: t for c, t in self._codes.items() if t > now}

    def issue(self) -> str:
        self._purge()
        code = secrets.token_urlsafe(18)
        self._codes[code] = time.monotonic() + self.TTL_S
        return code

    def redeem(self, code: str | None) -> bool:
        self._purge()
        return bool(code) and self._codes.pop(code, None) is not None


class TokenAuthMiddleware:
    """Pure ASGI middleware so it covers http and websocket scopes alike."""

    def __init__(self, app, token: str, port: int, login_codes: LoginCodes):
        self.app = app
        self.token = token
        self.login_codes = login_codes
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _ok(self, candidate: str | None) -> bool:
        return bool(candidate) and hmac.compare_digest(candidate.encode(), self.token.encode())

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        h = _headers(scope)
        if h.get("host", "") not in self.hosts:
            return await self._deny(scope, send, 403, "Host not allowed")

        auth = h.get("authorization", "")
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        if self._ok(bearer):
            scope["sekantor_auth"] = "bearer"
            return await self.app(scope, receive, send)

        cookie = SimpleCookie(h.get("cookie", ""))
        from_cookie = cookie[COOKIE].value if COOKIE in cookie else None
        if self._ok(from_cookie):
            method = scope.get("method", "GET")
            if scope["type"] == "websocket" or method not in SAFE_METHODS:
                if h.get("origin") not in self.origins:
                    return await self._deny(scope, send, 403, "Cross-origin request refused")
            scope["sekantor_auth"] = "cookie"
            return await self.app(scope, receive, send)

        # One-time login link: /?login=<code> sets the cookie; the code is then spent.
        if scope["type"] == "http" and scope.get("path") == "/":
            q = parse_qs(scope.get("query_string", b"").decode())
            if self.login_codes.redeem((q.get("login") or [None])[0]):
                await send({"type": "http.response.start", "status": 303, "headers": [
                    (b"location", b"/"),
                    (b"set-cookie", f"{COOKIE}={self.token}; HttpOnly; SameSite=Strict; Path=/".encode()),
                    (b"cache-control", b"no-store"),
                ]})
                return await send({"type": "http.response.body", "body": b""})
        return await self._deny(scope, send, 401, "Not signed in. Run `sekantor open` for a fresh link.")

    async def _deny(self, scope, send, status: int, message: str):
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
        body = json.dumps({"error": message}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
