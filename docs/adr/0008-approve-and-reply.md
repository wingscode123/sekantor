# ADR-0008: Approve, deny and reply from Ronda (Claude Code)

- Status: Superseded by ADR-0021
- Date: 2026-11-11
- Evidence: docs/spike/m2-actions.md

## Context
FR-20 to FR-22. M2 spike (interactive Claude Code 2.1.322): a waiting PermissionRequest hook does
not hide the terminal's permission menu; a hook decision answers the menu; an answer in the terminal
first wins and a later hook decision is ignored. An async Stop hook with `asyncRewake` that exits 2
wakes the idle agent with its stderr shown as "Stop hook feedback", which Claude acts on.

## Decision
- **Approve/deny**: PermissionRequest runs **synchronously**. After posting its event it long-polls
  `GET /v1/sessions/{id}/actions/next?for=approval&request_id=…` for up to `approval_wait`
  (default **600 s**, `~/.ronda/config.toml`; 0 turns Ronda approvals off). FR-21's default of 0 is
  superseded: waiting cannot hang the agent because the terminal or host prompt stays usable.
  Only an explicit action for that exact request id produces a decision; anything else (timeout,
  hub down, session moved on, error) prints nothing: the agent's own prompt decides. Never auto-approve.
- **Reply**: Stop runs **async with asyncRewake**. It long-polls for a reply for up to `reply_wait`
  (default 1800 s); a reply exits 2 with the text on stderr. The turn ends normally meanwhile.
  Offered only where verified: Claude Code in a terminal (`CLAUDE_CODE_ENTRYPOINT=cli`). SDK hosts
  (Orca chat, Claude desktop, VS Code, OpenBot) do not get `reply` until tested (FR-25 hides it).
- **Request ids**: the PermissionRequest and Stop events carry `request.id` (their own `event_id`;
  `request.kind` is `tool` or `input`). Actions name the `request_id` they answer. The hub refuses an
  action for a request that is no longer pending, and wakes waiting hooks when the session moves on
  so stale hooks exit.
- **Risky commands** (Security section): approving a command that matches the denylist
  (`rm -rf`, `git push --force`, ...) needs `confirm: true`; the UI asks a second time.

## Consequences
- One idle Python process per session waiting for a reply (roughly 15-30 MB each).
- A reply reaches Claude as hook feedback, not a typed message.
- Existing installs need `ronda install claude` again (doctor flags the old hook shape).
