# ADR-0009: Native desktop notifications from the hub (Kentongan)

- Status: Accepted (owner, 2026-11-11)
- Date: 2026-11-11

## Context
FR-30: notify on a move to `waiting_*`, `error` (and `done`). The inbox tab may be closed.

## Decision
The hub sends OS notifications with no extra dependency: a WinRT toast through PowerShell on
Windows, `osascript` on macOS, `notify-send` on Linux when present. Fired in the background, never
blocking the hub. Rules: notify on a move into `waiting_approval` or `error`, and into
`waiting_input` only from `running` (a finished turn; a fresh session is not news). At most one
notification per session per 10 s. On by default; `notify = false` in `~/.ronda/config.toml` or
`ronda up --no-notify` turns it off. Notification text holds the agent, host and project only, never
the tool input (it can contain secrets).

## Consequences
- A failure to notify is logged and ignored.
- Telegram and webhooks (M3) reuse the same rules.
