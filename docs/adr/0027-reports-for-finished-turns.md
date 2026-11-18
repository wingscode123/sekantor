# ADR-0027: Reports for finished turns

- Status: Accepted
- Date: 2026-11-18

## Context

The office treated finished Claude Code turns as requests for input. That put agents who had only finished their work in the same queue as agents who needed approval or an answer.

## Decision

Event schema v1 adds status `reported` and request kind `report`. The inbox orders reports after `running` and before `done`. Claude Code Stop reports its last assistant message, including when the text reads like a question. An idle_prompt notification leaves the current status and summary intact. Explicit input notifications and OpenBot prompts carry request kind `question`. tmux reports when it detects an idle agent. OpenBot continues to use `done` for idle agents.

Only approval, explicit input, and error require attention. Reports produce no desktop notification. The hub exposes `report_pending` while a report is unread. The authenticated `POST /v1/sessions/{id}/acknowledge` records `acknowledged_at` and broadcasts the session update. Accept marks the report read locally. An accepted agent goes to the pantry and a later report requires a new acknowledgement.

## Consequences

Existing event records remain valid. Consumers that enumerate statuses or request kinds must recognize the new values before ingesting new reports. Older sessions with a generic input marker are treated as idle for attention purposes.
