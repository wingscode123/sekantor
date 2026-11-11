# ADR-0005: Host fingerprint scoring (hosts.yaml)

- Status: Accepted
- Date: 2026-11-11

## Context
FR-08/FR-09: label each agent with its host app, with a confidence and the signals that decided it,
from rules the community can extend. M0 probes on Windows showed strong, cheap signals per host:
`CLAUDE_CODE_ENTRYPOINT` (`cli`, `sdk-ts`, `claude-desktop`, `claude-vscode`, `openbot`),
`ORCA_*` env vars, `TERM_PROGRAM`, `VSCODE_PID`, and the parent process name.

## Decision
`hosts.yaml` holds per-host signals (env var / parent name / exe path / cwd / cmdline regex) with
weights. Confidence = 1 − Π(1 − weight) over matched signals; highest wins, file order breaks ties;
below 0.5 falls back to `terminal` / `unknown`. Matched signal ids become `host.via`.

## Consequences
- Validated against all M0 evidence (9 probe processes, 7 SessionStart payloads): all correct.
- Rules for macOS/Linux terminals and Cursor/JetBrains are unverified guesses (`verified: []`).
- The host answers "which app do I open?", not "which transport can act?" (tmux inside Orca
  is labelled Orca). Transport/capabilities stay with the pos.
