# ADR-0017: Fixes from the first dogfooding run

- Status: Accepted
- Date: 2026-11-12

## Context
First real-use run (2026-11-11, 10 h): 3177 events sent, 2199 stored, 1 lost, 977 not delivered
because the hub was off most of the morning; 47 sessions, 37 of them "OpenBot"; "waited for a reply"
10 h 41 min; approvals clicked on Claude's questions came back `expired` and `superseded`.

## Decision
1. **SessionEnd budget**: the lost event was a SessionEnd cut by Claude Code's shared 1.5 s budget
   under load. The hook gets `timeout: 5` (raises the budget) and a 1.5 s HTTP timeout.
2. **OpenBot helper runs** (28 sessions) start Claude Code in OpenBot's program folder. The hook
   ignores folders matching `ignore_cwd` (config.toml; default: OpenBot's install folders).
3. **Stats**: the FR-07 sweep now writes a `session_ended` event, so timelines and `ronda stats` see
   the end. Stats splits waits into *answered* (the agent moved on; total, count, median) and
   *left waiting* (the session ended or is still waiting), and clips waits at the session's end.
4. **AskUserQuestion** reaches hooks as a PermissionRequest; approving it does not answer it. It is
   now `waiting_input` with `request.kind = "question"` and the question as summary, no Approve/Deny,
   "Answer it in <app>"; the permission notification that follows does not turn it back into an approval.
5. **Hub always on**: `ronda service install` registers a login task (Windows Task Scheduler XML with
   no run limit and restart on failure, launchd agent, or systemd user unit) running
   `ronda up --no-open --log-file ~/.ronda/hub.log` with no window. `doctor` warns when it is missing.

6. **Children end with the hub**: a force-stopped hub (Task Scheduler's End, a crash) runs no
   cleanup, which left the relay and pos processes running. `ronda up` passes its PID and start time;
   each child checks them every 5 s and exits when the hub is gone (`ronda.lifeline`).

## Consequences
- Existing installs need `ronda install claude` again for the SessionEnd budget; doctor flags it.
- `ronda stats` numbers are not comparable with the first run's "waited" line.
