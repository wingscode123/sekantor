# ADR-0011: Telegram and webhooks live in a separate relay process

- Status: Accepted (owner, 2026-11-11)
- Date: 2026-11-11

## Context
M3 adds Telegram (FR-31) and generic webhooks (FR-32). Both need outbound network access. The
brief's non-negotiable: no outbound network calls from the hub.

## Decision
`ronda relay` is its own process and a plain client of the hub: it follows `WS /v1/stream` and posts
actions to `POST /v1/sessions/{id}/actions` with the local token, channel `telegram` (or `webhook`
for logging). It is the only Ronda process that talks to the internet. `ronda up` starts it as a
child process only when Telegram is paired or a webhook is configured, and stops it on exit;
`ronda up --no-relay` skips it. The hub stays offline.

## Consequences
- A relay crash never affects the hub, the hooks, or the agents.
- The same notification rules as desktop notifications (ADR-0009) decide what is sent.
- The relay keeps only in-memory state (message ids to requests); after a restart, old Telegram
  buttons answer "This request is no longer open."
