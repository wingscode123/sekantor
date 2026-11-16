# ADR-0022: Optional `activity` field in event schema v1

- Status: Accepted
- Date: 2026-11-16

## Context
SeKantor animates each agent's avatar by what it is doing (reading, editing, running a command, browsing
the web). Events carry only a free-text `summary` ("Bash: npm test"), which is not a stable thing to
parse. The PreToolUse hook knows the tool name, so the pos can say it outright.

## Decision
Add an optional, backward-compatible field to schema v1:
```json
"activity": { "tool": "Bash", "kind": "run" }
```
`kind` is one of `read`, `edit`, `run`, `web`, `other`; `tool` is at most 100 characters. The Claude Code
pos sets it on `PreToolUse` only, mapping tools by name (`Read`/`Grep`/`Glob`/`LS`/`NotebookRead` read;
`Edit`/`MultiEdit`/`Write`/`NotebookEdit` edit; `Bash`/`BashOutput`/`KillShell`/`PowerShell` run;
`WebSearch`/`WebFetch` web; anything else, including MCP tools and subagents, `other`).

The hub keeps the last activity per session while the status stays `running` (PostToolUse carries none)
and clears it on any other status. `session_json` exposes it as `activity` (`{"tool","kind"}` or null).

## Consequences
- Old pos without `activity` still work; their sessions show `activity: null`.
- Old hubs ignore the field (`extra="ignore"`), so the schema stays v1.
- A new tool name never errors; it is `other` until the table learns it.
