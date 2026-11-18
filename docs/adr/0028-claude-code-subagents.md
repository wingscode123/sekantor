# ADR-0028: Claude Code subagents

- Status: Accepted
- Date: 2026-11-18

## Context

Claude Code supplies the parent session ID and a worker ID in its subagent hooks. A worker's tool use and report belong to that worker, while the parent reports its own turn separately.

## Decision

Event schema v1 adds optional `subagent: {id, type?}` and three event types. `SubagentStart` becomes `subagent_started`, a `PreToolUse` with an agent ID becomes `subagent_activity`, and `SubagentStop` becomes `subagent_ended` with the worker's last assistant message as its summary. The installer registers both lifecycle hooks as asynchronous commands in exec form.

The hub folds the events into the parent's `subagents` list while preserving the parent's status, activity and summary. Each worker starts as `working`, then becomes `reported` at stop. An activity or stop can create a worker if the start arrives late or is missing. If Claude Code omits the worker type, the hub uses `unknown` until it receives a type.

A worker's `PermissionRequest` or `permission_prompt` notification makes the parent wait for approval. The request records the worker ID and type. A worker's `PostToolUse`, `PostToolUseFailure` or `PermissionDenied` returns the parent to running only when it owns the pending approval. Other hook payloads carrying a worker ID are ignored.

Session responses list working workers before reported workers. A stopped worker's activity clears and its report remains visible for 60 seconds from `ended_at`. The store filters expired reports on read and drops them from stored session state on the next event for that session.

## Consequences

The upgraded hub accepts older events and reads existing session records. The new hook integration requires an upgraded hub to accept the new event types. Upgrade the hub first, then reinstall the Claude Code hooks to register the lifecycle events.
