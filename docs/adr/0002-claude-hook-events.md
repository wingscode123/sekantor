# ADR-0002: Claude Code hook events used for status

- Status: Proposed (needs owner OK: differs from the PRD's list of 5 hooks)
- Date: 2026-11-11

## Context
The PRD lists `PreToolUse`, `Notification`, `Stop`, `SessionStart`, `SessionEnd`, and plans
approval as a long-poll in `PreToolUse` (FR-20). The M0 spike (docs/spike/claude-hooks.md) found:
- `PreToolUse` fires for *every* tool call, including ones that are auto-allowed. It cannot tell
  whether the user is being asked.
- `PermissionRequest` fires only when Claude Code is about to ask for permission (also in `-p`
  and SDK-hosted sessions, where it races the host's own dialog: "whichever decides first applies").
- `Notification`/`permission_prompt` fires only after ~6 s, and not at all if someone answers first.
- Without `UserPromptSubmit` a session never leaves `waiting_input` when the user replies in the
  source app. Without `PostToolUse` it never leaves `waiting_approval` after the user approves there.
- `StopFailure` is the only signal for a turn that died on an API error.
- `SubagentStop` fires after the main `Stop` for internal helpers (`agent_type: ""`, e.g. the
  next-prompt suggestion); it must not change the session status.

## Decision
Register `ronda-hook` for: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`,
`PostToolUse`, `PostToolUseFailure`, `PermissionDenied`, `Notification`, `Stop`, `StopFailure`,
`SessionEnd`. Mapping:

| Hook | Status |
| --- | --- |
| SessionStart | `waiting_input` if `source` is `startup`/`clear`, else unchanged/`running` |
| UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, PermissionDenied | `running` |
| PermissionRequest | `waiting_approval` |
| Notification `permission_prompt` | `waiting_approval` |
| Notification `idle_prompt` / `agent_needs_input` / `elicitation_dialog` | `waiting_input` |
| Stop | `waiting_input` |
| StopFailure | `error` |
| SessionEnd | `ended` |

M2 approval uses `PermissionRequest` (`decision.behavior`), not a `PreToolUse` long-poll.

## Consequences
- Fewer false "waiting" states and no added latency on auto-allowed tools.
- An interrupted turn (Esc) fires no `Stop`; the session stays `running` until the next event.
- PRD FR-20 wording needs an update once accepted.
