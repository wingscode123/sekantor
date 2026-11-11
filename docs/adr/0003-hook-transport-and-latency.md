# ADR-0003: ronda-hook transport and latency budget

- Status: Proposed
- Date: 2026-11-11

## Context
Budget: < 100 ms hook overhead in the happy path, hard timeout 2 s, never block or change
Claude Code's behaviour when the hub is down. The M0 capture hook (Python + psutil walking the
full parent chain) took **150-900 ms, up to 3 s** on Windows under load.
Options considered:
1. `type: "http"` hook straight to the hub: no process spawn, but cannot compute a parent chain,
   and a down hub shows up as a hook error.
2. Command hook, synchronous, stdlib only.
3. Command hook with `async: true` for observe-only events: Claude Code does not wait at all.

## Decision
- Command hook (`ronda-hook`), stdlib only on the hot path (`json`, `urllib`, `os`). psutil is
  imported lazily and only on `SessionStart`, to send the parent chain + env fingerprint once.
  Later events send only the cheap env subset and `CLAUDE_PID`.
- In M1 every registration is `async: true` except `SessionEnd`, which runs synchronously with a
  0.5 s HTTP timeout so it fits the 1.5 s SessionEnd budget. (M2 decision hooks will be sync.)
- HTTP POST timeout 0.5 s connect / 1.5 s total; the hook process exits by 2 s no matter what.
- Always exit 0 with empty stdout. All exceptions are swallowed; failures are appended to
  `~/.ronda/hook.log` (size-capped).

## Consequences
- Zero added latency on observe-only events; one ~100-300 ms cost on SessionStart in the background.
- In `-p` mode async hooks still running at teardown are killed; a lost event there is acceptable.
- `CLAUDE_PID` (set by Claude Code in the hook env) gives the agent PID for FR-07 liveness checks
  without walking the process tree.

## M1 measurements (Windows 11, machine under heavy load)

- Bare `python -c pass`: 540-840 ms during the test run (normally 40-60 ms); `ronda-hook` adds
  about 100 ms on top of the interpreter start.
- Removed from the hot path after profiling: `urllib.request` (pulls in `http.client` and `email`;
  replaced by a plain socket POST to loopback) and `yaml` (rules cached as JSON in
  `~/.ronda/hosts.cache.json`, keyed on the rules file's path and mtime).
- SessionStart posts first with the env-only fingerprint, then sends a follow-up event with the
  parent-chain fingerprint, so the card appears without waiting for psutil.
- End to end (`scripts/e2e_claude.py`, a real `claude -p` session): hook timestamp to WebSocket
  arrival 16-51 ms; worst 83 ms in earlier runs. Status sequence
  waiting_input -> running -> waiting_input -> ended.
- Because every hook except SessionEnd is `async: true`, Claude Code does not wait for any of this.
