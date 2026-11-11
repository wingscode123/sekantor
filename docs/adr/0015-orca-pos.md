# ADR-0015: Orca pos for non-Claude agents, opt-in

- Status: Accepted
- Date: 2026-11-11

## Context
FR-05. M0 showed Claude Code in Orca (chat and terminal) already reaches Ronda through its hooks,
and an Orca chat can take replies (M4 check). What is left is other agents Orca runs in its
terminals. The `orca` CLI exposes `terminal list` (with `agentIdentity`, `preview`, `incarnationId`,
`worktreePath`) and `terminal send`, but each call took tens of seconds on a busy machine.

## Decision
`ronda pos orca` reuses the tmux pos's screen logic: one `orca terminal list --json` per 10 s cycle,
status from `preview` and its changes, answers with `orca terminal send` (text and Enter separately).
Session id `orca:<terminal handle>:<hash of incarnationId>`; a new run in the same terminal is a new
session. It is opt-in (`orca_pos = true` in config.toml) so Ronda never loads Orca's CLI for nothing.

## Consequences
- Orca's own agent hooks remain the source for Claude in Orca; no session is listed twice.
- Same screen-pattern caveats as the tmux pos (ADR-0013).
