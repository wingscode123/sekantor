# ADR-0029: Floors and Orca teams

- Status: Accepted
- Date: 2026-11-18

## Context

Claude Code can run in several hosts, including Orca. Orca's main checkout holds the project lead, and its linked worktrees hold juniors. Claude's native subagents still belong to the Claude session that started them, as described in ADR-0028.

## Decision

Session JSON adds `floor`, `team` and `report_to`. OpenBot takes precedence when either source or host is OpenBot. Orca comes next, and all other sessions appear on the Claude floor.

The Claude hook and native forwarder capture the allowlisted `ORCA_AGENT_SESSION_ID` and `ORCA_TERMINAL_HANDLE`. The optional event `orca` object carries a session ID, project, worktree, main-checkout flag, creator and model. An `orca_placement` event updates a separate SQLite table keyed by Orca session ID. Placements expire two minutes after receipt and never create avatars. Worker session events carry their own team data.

Orca team placement takes precedence over the bounded local Git inspection already cached with project detection. A `.git` directory identifies a main checkout and a `.git/worktrees` pointer identifies a linked checkout. When neither placement nor Git identifies a team, the session has a null team. A junior's creator identity selects the matching active Orca session when available. Otherwise, the most recently active main-checkout session in the project takes precedence.

A reported junior with a resolved lead routes to that lead with `report_pending` false. Leads and juniors without a resolved lead can report to the user. Questions, approvals and errors continue to need the user's attention. Team updates leave the lead's own session status, activity and summary intact.

## Consequences

Older stored sessions and event producers remain compatible. Start the upgraded hub to regenerate the native hook allowlist. The hub uses local event and checkout data throughout. Orca CLI calls belong to the opt-in Orca pos.
