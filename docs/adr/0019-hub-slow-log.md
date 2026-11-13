# ADR-0019: The hub logs where the time went when it is slow; the service log is rotated

- Status: Accepted
- Date: 2026-11-13

## Context
Dogfooding showed 770 hooks timing out ("hub unreachable") while the hub was running: their events
arrived 13 s to 163 s late, in bursts of heavy agent activity. A burst of 32 parallel posts against a
copy of the real database stayed under 0.2 s, so the cause showed only under real load and could not
be found from the code. Meanwhile `hub.log` had grown to 11 MB of repeated "OpenBot not reachable" lines.

## Decision
- The hub logs three things, each only past 1 s (the hook's own HTTP timeout, `store.SLOW_S`):
  an event loop that woke up late ("event loop was blocked for N s"), the store lock's wait and hold
  time per event, and `POST /v1/events` requests whose events were sent long before ("sent N s ago").
- The OpenBot pos logs only when OpenBot becomes unreachable or reachable again, not on every poll.
- `ronda up --log-file` moves a log over 5 MB to `<name>.1` when it starts.
- `hook.log` names the event in a "hub unreachable" line, so `ronda stats` counts it as not
  delivered however late the hook got to write it (one event was logged 7 s late and counted as lost).

## Consequences
- The log stays silent in normal use and points at the cause when the hub stalls.
- The log is rotated only at start-up, so a hub that runs for weeks can grow it past 5 MB until the
  next start.
