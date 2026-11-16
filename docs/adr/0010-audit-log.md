# ADR-0010: Actions are the audit log

- Status: Superseded by ADR-0021
- Date: 2026-11-11

## Context
FR-24: every action is recorded (who, when, from which channel, content).

## Decision
Every action posted to the hub is a row in the SQLite `actions` table: id, session, request id,
type, text, channel (`web`, `cli`, `api`), actor (local OS user), created_at, and its outcome
(`pending`, `delivered`, `superseded`, `expired`) with the time it changed. Rows are kept for 90 days
(events: 7). `GET /v1/sessions/{id}/actions` and `ronda audit` read it.

## Consequences
- The table is append-only from the API's point of view; only the outcome columns change.
