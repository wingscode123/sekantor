# ADR-0001: Python 3.11 + FastAPI + SQLite for the core

- Status: Accepted
- Date: 2026-11-11

## Context
PRD open question: Python (fast to build, matches the stack) or Go/Rust (single binary).
The kickoff brief fixes the M1 stack: Python 3.11+, FastAPI, SQLite, WebSocket, Typer, React+Vite.

## Decision
Python 3.11+ for hub, CLI and the Claude Code pos. Packaged with `uv`/`pipx` as `ronda`
with console scripts `ronda` and `ronda-hook`. SQLite via the stdlib `sqlite3` module.

## Consequences
- Contributors can write a pos in Python in-process, or in any language by POSTing to `/v1/events`.
- Python interpreter start-up (~40-60 ms on Windows) is part of every hook call. See ADR-0003
  for how the hook stays inside its latency budget.
- Distribution is not a single binary; revisit only if install time (≤ 5 min) is missed.
