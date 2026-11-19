# Attention radar and daily standup

Date: 2026-11-19. Status: approved by the owner (brainstorm, directions 1 and 2).

## Why
SeKantor pivoted from the Ronda inbox because the owner kept waiting in the source apps. The owner
looks at the office **when they know agents are running**, not when an agent is waiting for them. So:
- the office must reach the owner when someone waits, without the owner looking at it (A), and
- the owner needs a cheap answer to "what happened while I was away / today?" (B).

Both build on data the hub already has: `status`, `status_since`, `needs_you`, `report_to`,
`snoozed_until`, events in the store, `sekantor stats`. No LLM, nothing leaves the machine
(webhooks keep their existing opt-in behaviour).

## A. Attention radar

"Waiting for you" = `needs_you` is true and `report_to == "you"` and not snoozed. Wait time =
now - `status_since`.

- **A1 Tab and window title.** `document.title` = `(N) SeKantor` while N > 0, plain `SeKantor`
  otherwise. The favicon gets a small badge dot while N > 0 (canvas-drawn from the existing icon,
  brand palette). The Tauri window shows the page title, so it carries over.
- **A2 Waiting levels.** calm < 2 min, restless 2-10 min, urgent >= 10 min (constants in one
  place). The waiting avatar's bubble/animation changes with the level (palette only: Gold ->
  Apricot -> a stronger warm accent already in the palette), and its name plate shows the wait
  (`3m`, `1h 5m`). Respect `prefers-reduced-motion` (level shown by colour/text, no faster motion).
- **A3 Queue at your desk.** Avatars that wait for you stand in a queue at your desk, longest wait
  first. A header pill shows `2 waiting · longest 7m`; clicking it opens the card of the longest
  waiter. The mini view (always-on-top window) shows the same count and longest wait.
- **A4 Reminder.** The hub sends one reminder notification (desktop + matching webhooks, through the
  existing Notifier) when a session has been waiting for you for `remind_after_minutes`
  (config.toml, default 10, 0 = off). One reminder per waiting episode (a new status resets it);
  snooze suppresses it. The check runs in the hub's existing periodic sweep, not per request.

## B. Daily standup ("Rapat")

- **B1 Hub.** `GET /v1/digest?since=<iso8601>` (bearer or cookie, read-only). Default `since` =
  local midnight today. Deterministic, from the store:
  - totals: agents active in the window, turns finished, times you were asked (approvals +
    questions), total and longest time they waited for you, errors, sessions still waiting now;
  - per session active in the window (grouped by project, then floor): agent name/model, project,
    first and last activity, turns finished, tool activity counts by kind (the existing activity
    kinds), times it asked you and its total wait, errors, its latest summary/report text
    (truncated), current status.
  Must stay fast (target < 200 ms for a day of the owner's data: ~40 sessions, ~20k events); use
  SQL over the events table with an index-friendly time filter, not a Python scan of everything.
- **B2 CLI.** `sekantor digest [--since today|8h|2026-11-19T08:00] [--json]`, reusing
  `stats.parse_since` style parsing; prints totals then one line per session, waiting ones first.
- **B3 Web.** A `Rapat` (standup) button in the header opens a panel: totals on top, then cards per
  project/agent, waiting-for-you first. Clicking an agent opens its existing card. Range switch:
  Today / Last 8 h.
- Parked: automatic end-of-day notification, LLM-written summaries, history/replay.

## Out of scope
Changing the watch-only rule (ADR-0021), restyle (S3), multi-user.
