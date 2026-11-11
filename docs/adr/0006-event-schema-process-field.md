# ADR-0006: Optional `process` field in event schema v1

- Status: Accepted (owner, 2026-11-11)
- Date: 2026-11-11

## Context
FR-07: a session is `ended` when it sent no event for more than 10 minutes **and** its process is
gone. The PRD's schema v1 has no place for the agent's PID. Claude Code exposes it to hooks as
`CLAUDE_PID` (M0 evidence); Claude desktop restarts the CLI on resume, so the PID can change
within one `session_id`.

## Decision
Add an optional, backward-compatible field to schema v1:
```json
"process": { "pid": 69420 }
```
The hub keeps the latest PID per session. The sweep marks a session `ended` when it has been silent
for 10 minutes and either its PID is no longer alive, or it never reported a PID.

## Consequences
- Pos without a PID still work; their sessions end on the timeout alone.
- A long-idle session whose process is alive stays in the inbox (correct: it still waits for you).
- PID reuse by the OS could keep a dead session alive; acceptable for M1.
