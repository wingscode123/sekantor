# ADR-0007: Token on every request, cookie bootstrap for the browser

- Status: Accepted
- Date: 2026-11-11

## Context
The hub must require the local token (`~/.ronda/token`, mode 600) on every request, including the
static web UI and the WebSocket. Browsers cannot set headers on a WebSocket, and pasting a token into
a page is clumsy. The hub binds to 127.0.0.1, but a malicious web page can still reach loopback
(CSRF, DNS rebinding).

## Decision
One pure ASGI middleware guards http and websocket scopes:
- `Authorization: Bearer <token>` for pos, hooks and the CLI.
- `ronda up` prints and opens `http://127.0.0.1:7878/?token=…`. The hub sets an `HttpOnly;
  SameSite=Strict` cookie and redirects to `/`, so the token leaves the address bar.
- Cookie-authenticated requests that change state, and every WebSocket, must carry an `Origin` of the
  hub itself.
- The `Host` header must be `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding guard).
- Unauthenticated requests get 401 (HTTP) or close code 4401 (WebSocket). No route is exempt.

## Consequences
- Opening `http://127.0.0.1:7878/` without the link shows a 401 that says to use `ronda up`.
- No OpenAPI docs are served (they would need an exemption).

## Update (M4)
The login link no longer carries the token: `ronda up` and `ronda open` print `/?login=<code>`, a
one-time code valid for 10 minutes, kept in the hub's memory (`POST /v1/login-code`, bearer only).
`/?token=` is no longer accepted. `ronda token rotate` replaces the token.
