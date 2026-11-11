# ADR-0013: tmux pos reads the screen and answers with send-keys

- Status: Accepted
- Date: 2026-11-11

## Context
FR-04 and FR-23: CLI agents without hooks (codex, opencode, gemini, aider) in tmux panes. The only
signals are the process tree and what the pane shows.

## Decision
- `ronda pos tmux` (started by `ronda up` when `tmux` is on PATH) scans `tmux list-panes -a` every
  2 s, finds an agent in each pane's process tree, and reads the last lines with `capture-pane`.
- Status from the screen, rules in `src/ronda/pos/tmux/agents.yaml`: a question pattern in the last
  4 non-empty lines means `waiting_approval`; a still screen ending at a prompt for 4 s, or still for
  30 s without one, means `waiting_input`; otherwise `running`. The request id is a hash of the
  screen, so a new question is a new request.
- Answers: approve/deny send the agent's configured keys; reply types the text literally then
  Enter. Before sending, the pos checks the pane still runs the same agent PID (FR-23); otherwise
  nothing is sent.
- Claude Code panes are skipped by default (its hooks report it), so a session is not listed twice.
- Session id `tmux:<pane id>:<agent pid>`; host `tmux` with confidence 1.

## Consequences
- The prompt patterns are unverified guesses (PRD risk: text detection can be wrong). They live in
  YAML so users can correct them; the end-to-end test uses a fake agent.
- Not available on Windows without WSL.
