# ADR-0016: Open in source, snooze, quiet hours

- Status: Accepted
- Date: 2026-11-11

## Context
FR-14 (P1) "Open in source"; FR-15 (P2) snooze per agent; FR-33 (P2) debounce and quiet hours.

## Decision
- **Open** (`POST /v1/sessions/{id}/open`, button "Open in <host>"): the hub brings the app forward
  without a shell and without the network: `vscode://file/<path>` / `cursor://file/<path>` URLs handed
  to the OS; `orca terminal switch` (Orca pos sessions) or `orca worktree activate --worktree path:`;
  `tmux switch-client` + `select-pane`; OpenBot and Claude desktop started (single instance, so they
  come to the front); otherwise the project folder in the file manager. Sessions carry `open_label`
  (`null` when there is no way). Refused from channel `telegram`: it acts on this computer only.
- **Snooze** (`POST`/`DELETE /v1/sessions/{id}/snooze`, minutes or until unmuted; `ronda snooze`):
  stored on the session as `snoozed_until`; new events keep it. A snoozed session sends no desktop,
  Telegram or webhook notification and moves to a "Snoozed" group. It is still listed and answerable.
  OpenBot sessions are per agent, so snoozing one mutes that agent.
- **Quiet hours** (`quiet_hours = "22:00-07:00"` in config.toml, local time, may cross midnight):
  no notifications in that window; the inbox still updates and Telegram messages already sent are
  still closed when answered. Debounce: one notification per session per 10 s (ADR-0009).

## Consequences
- `snoozed_until` and `open_label` are additions to the session API, not to event schema v1.
