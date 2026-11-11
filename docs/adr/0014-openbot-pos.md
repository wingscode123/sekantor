# ADR-0014: OpenBot pos through OpenBot's Local scripts API

- Status: Accepted
- Date: 2026-11-11
- Source: nightly-labs/openbot `docs/automation.md`, the bundled `resources/cli/openbot-cli.mjs`

## Context
FR-06. OpenBot agents run Claude Code with `--setting-sources=project,local`, so Ronda's user-level
hooks never reach them (M0). OpenBot offers a loopback API per agent ("Local scripts", off by
default) with the agents' pending approvals, questions and browser takeovers, and endpoints to answer
approvals and questions.

## Decision
- `ronda pos openbot` (started by `ronda up` when OpenBot is installed) polls every 3 s:
  `GET /v1/agents`, then `GET /v1/agents/{id}/pending`. Reads are not rate limited by OpenBot.
- One session per agent, `openbot:<agent id>`, host `openbot` with confidence 1.
  An approval is `waiting_approval` (Approve/Deny -> `approvals/{id}/respond` accept/decline).
  A prompt with exactly one question is `waiting_input` with reply (-> `prompts/{id}/answer`).
  Secret questions, multi-question prompts and browser takeovers are shown without buttons
  ("answer in OpenBot"). Nothing pending is `done` ("Idle").
- Ronda never sends a new message to an idle agent: that is not an answer, and it counts against
  OpenBot's hourly limit.
- URL and token are read from `<userData>/automation/` on every reconnect and on 401 (OpenBot
  rotates both on each start). The token is never logged. Requests carry no Origin header.
- When the files disappear (Local scripts off everywhere, or OpenBot quit) the sessions end.

## Consequences
- Users must turn on Local scripts per agent; `ronda doctor` says so.
- OpenBot exposes no "running" state; an agent at work shows as Idle until it asks for something.
