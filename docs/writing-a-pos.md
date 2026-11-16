# Writing a pos

A *pos* (as in *pos ronda*, the watch post) is Ronda's adapter for one platform. It tells the hub
what the platform's agents are doing. It only watches (ADR-0021): people answer in the agent's own
app, so a pos never receives an answer. Ronda's core knows only the event schema; everything
platform-specific lives in the pos.

Start from [`examples/pos_minimal.py`](../examples/pos_minimal.py): about 50 lines, standard library
only.

## Report what your agents are doing

`POST /v1/events` with schema v1 events
([`src/ronda/schema.py`](../src/ronda/schema.py)).

| Field | What to put there |
| --- | --- |
| `session_id` | Stable for one run of one agent, prefixed with your pos: `mypos:<id>` |
| `source` | The agent (`codex`, `aider`, ...) |
| `type` | `session_started`, `status_changed`, `message`, `session_ended` |
| `status` | `running`, `waiting_approval`, `waiting_input`, `error`, `done`, `ended` |
| `request` | When waiting: `{"kind": "tool", "input": "<command>"}` or `{"kind": "input"}` |
| `host` | Where the agent runs: `{"app": "<name>", "confidence": 0..1, "via": ["<signal>"]}` |
| `process` | `{"pid": n}` if you know it: Ronda then ends the session when the process is gone (FR-07) |
| `ts` | When it happened (UTC). Ronda orders by it, so late events never undo newer ones |

Send an event when the state changes, not on a timer. Repeat events are harmless (`event_id` makes
them idempotent).

`capabilities` and `request.id` are deprecated: the hub still accepts them and ignores them.

## Auth and safety

- Read the token from `~/.ronda/token` and send `Authorization: Bearer <token>`. The hub listens on
  `127.0.0.1:7878` only.
- Never send anything to the internet from a pos unless that is the platform itself.
- Never answer an agent: no keys typed into a terminal, no approval calls. A pos only watches.

## A process of its own

Every pos, the official ones too, is a separate process that talks to the hub over HTTP. A crash in
one never touches the hub, and a pos can be written in any language. `ronda up` starts the official
ones.

## Examples in this repo

| Pos | How it sees agents |
| --- | --- |
| `pos/claude_code` | Claude Code hooks (all asynchronous) |
| `pos/tmux` | `tmux capture-pane` + process tree |
| `pos/orca` | `orca terminal list` |
| `pos/openbot` | OpenBot Local scripts API `/pending` |

## Tests

Add fixtures of real platform output (redacted), and test against a live hub; see
`tests/test_example_pos.py` (a live hub) and `tests/test_openbot.py` (a fake platform API).
