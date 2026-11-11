# ADR-0004: Installing hooks next to other tools' hooks

- Status: Accepted
- Date: 2026-11-11

## Context
The user's `~/.claude/settings.json` already contains hooks from Orca (`orca-agent-hook.exe`
on 16 events). Claude Code merges hook entries across settings files and runs matching hooks in
parallel. During M0 hooks were tested only via project-level `.claude/settings.local.json`.

## Decision
- `ronda install claude` appends one matcher group per event; it never edits or reorders other
  entries. Our entries are recognised by the command path ending in `ronda-hook`.
- A timestamped backup is written next to the file before any change
  (`settings.json.ronda-backup-YYYYmmddHHMMSS`).
- `--project` writes `./.claude/settings.local.json`; `--global` writes `~/.claude/settings.json`.
  Default is `--project` until M1 is dogfooded.
- `ronda uninstall claude` removes only our entries and leaves empty event keys out.

## Consequences
- Coexists with Orca's own status hooks.
- OpenBot sessions run with `--setting-sources=project,local`, so a global install does not reach
  them. Covering OpenBot needs per-agent-dir install or the OpenBot pos (M4).
