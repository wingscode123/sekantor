# Writing a pos

A *pos* (as in *pos ronda*, the watch post) is Ronda's adapter for one platform. It tells the hub
what the platform's agents are doing, and hands answers back to them. Ronda's core knows only the
event schema; everything platform-specific lives in the pos.

Start from [`examples/pos_minimal.py`](../examples/pos_minimal.py): about 70 lines, standard library
only, and it already does both directions.

## The two halves

**1. Report** what your agents are doing: `POST /v1/events` with schema v1 events
([`src/ronda/schema.py`](../src/ronda/schema.py)).

| Field | What to put there |
| --- | --- |
| `session_id` | Stable for one run of one agent, prefixed with your pos: `mypos:<id>` |
| `source` | The agent (`codex`, `aider`, ...) |
| `type` | `session_started`, `status_changed`, `message`, `session_ended` |
| `status` | `running`, `waiting_approval`, `waiting_input`, `error`, `done`, `ended` |
| `request` | When waiting: `{"kind": "tool", "input": "<command>", "id": "<unique>"}` or `{"kind": "input", "id": ...}` |
| `capabilities` | What Ronda may do for this request: any of `approve`, `deny`, `reply`. Leave out what you cannot do: the UI hides it (FR-25) |
| `host` | Where the agent runs: `{"app": "<name>", "confidence": 0..1, "via": ["<signal>"]}` |
| `process` | `{"pid": n}` if you know it: Ronda then ends the session when the process is gone (FR-07) |
| `ts` | When it happened (UTC). Ronda orders by it, so late events never undo newer ones |

Send an event when the state changes, not on a timer. Repeat events are harmless (`event_id` makes
them idempotent).

**2. Answer** what the person decided: for each pending request, ask
`GET /v1/sessions/{session_id}/actions/next?for=approval|reply&request_id=<id>&wait=25`.

- `{"action": {"type": "approve" | "deny" | "reply", "text": ...}}`: do it, once.
- `{"action": null, "reason": "timeout"}`: ask again.
- `{"action": null, "reason": "resolved"}`: someone answered elsewhere, or the session moved on.
  Stop waiting.

Only act on an action that names your current request id. If you cannot be sure the target is still
the same agent (a terminal that now runs something else), do nothing: Ronda fails closed.

## Auth and safety

- Read the token from `~/.ronda/token` and send `Authorization: Bearer <token>`. The hub listens on
  `127.0.0.1:7878` only.
- Never send anything to the internet from a pos unless that is the platform itself.
- Never approve on your own. A pos only carries out what the person chose.

## In-process pos (Python)

A Python pos can also implement the `Pos` protocol in
[`src/ronda/pos/base.py`](../src/ronda/pos/base.py) (`discover`, `stream`, `act`). The official pos
are separate processes started by `ronda up`, for isolation: a crash in one never touches the hub.

## Examples in this repo

| Pos | How it sees agents | How it answers |
| --- | --- | --- |
| `pos/claude_code` | Claude Code hooks | hook output (PermissionRequest), asyncRewake (Stop) |
| `pos/tmux` | `tmux capture-pane` + process tree | `tmux send-keys` |
| `pos/orca` | `orca terminal list` | `orca terminal send` |
| `pos/openbot` | OpenBot Local scripts API `/pending` | `/approvals/{id}/respond`, `/prompts/{id}/answer` |

## Tests

Add fixtures of real platform output (redacted), and test both halves against a live hub; see
`tests/test_hook_actions.py` (`Hub` helper) and `tests/test_openbot.py` (a fake platform API).
EOF
mkdir -p .github/ISSUE_TEMPLATE && cat > .github/ISSUE_TEMPLATE/new-pos.md <<'EOF'
---
name: New pos request
about: Ask for (or offer) support for another agent or app
title: "pos: <platform>"
labels: pos
---

**Platform / agent**: name, version, link.

**How do you run it?** (terminal, IDE, desktop app, inside another tool)

**How could Ronda see its state?** Anything you know: hooks, a local API, log files, a CLI,
its process name, env vars. A `scripts/probe_hosts.py -o probe.json` run while it waits for you
helps a lot (check the file for secrets first).

**How could Ronda answer it?** (approve/deny, reply text, keys in a terminal, an API call)

**Will you write it?** See docs/writing-a-pos.md.
EOF
cd /d/Ronda && .venv/Scripts/python.exe -c "import ast;ast.parse(open('examples/pos_minimal.py').read());print(sum(1 for l in open('examples/pos_minimal.py') if l.strip()), 'non-empty lines')"