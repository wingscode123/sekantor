# ADR-0021: SeKantor watches and does not answer

- Status: Accepted
- Date: 2026-11-16
- Supersedes: ADR-0008, ADR-0010, ADR-0011, ADR-0012

## Context
Ronda could approve, deny and reply for an agent (ADR-0008), kept an audit log of those actions
(ADR-0010), and carried them to Telegram and webhooks through a relay (ADR-0011, ADR-0012). That meant
a PermissionRequest hook that held the agent's prompt open for up to 10 minutes, a Stop hook that
woke the agent, long-polls in the hub, keys typed into terminals and calls into OpenBot. Each of those
is a way for Ronda to hold an agent up or act for the person, and the replies were verified in only
two Claude Code entrypoints. The product is turning into SeKantor, a pixel office you watch: people
answer in the agent's own app.

## Decision
Ronda only watches. It never answers an agent and never waits for one.

- Every hook handler is `async` with `timeout` 10 (SessionEnd 5), with no arguments and no
  `asyncRewake`. The hook posts the event and prints nothing. PermissionRequest and Notification still
  report `waiting_approval` and `waiting_input`, now asynchronously.
- The hub has no `/actions` routes, no waiters and no audit log. A new database gets no `actions`
  table; an existing table is left alone.
- The tmux, Orca and OpenBot pos still detect prompts and report statuses and requests, but send no
  keys and make no answer calls.
- The settings `approval_wait`, `reply_wait`, `risky_commands` and `reply_entrypoints` are gone. An old
  `config.toml` that still has them is read without a problem.
- `ronda approve`, `deny`, `reply` and `audit` are removed. The web inbox shows where to answer
  instead of answer buttons.
- `Event.capabilities` and `Request.id` stay in the schema as deprecated fields: an older pos can still
  post them (the hub answers 202) and they are ignored.

## Consequences
- No hook can hang an agent, and the "fail closed" promise gets simpler: there is nothing to fail.
- An install from before this change (a `--wait` argument, a synchronous PermissionRequest, `asyncRewake`)
  is reported by `inspect().current_shape()` as not current, and `ronda doctor` tells the owner to
  reinstall. Meanwhile an old handler does not hang an agent: the new `ronda-hook` ignores `--wait` and
  exits at once.
- The relay (Telegram, webhooks, ntfy) loses the actions API it used for buttons. It is removed
  separately in the same release.
- Remote approval from a phone is gone. If it returns it will be a new decision.
