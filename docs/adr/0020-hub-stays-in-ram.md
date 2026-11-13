# ADR-0020: On Windows the hub keeps a hard minimum working set

- Status: Accepted
- Date: 2026-11-13

## Context
With the slow-log of ADR-0019 in place, a day of dogfooding logged 39 event-loop stalls of 1 s to
5.6 s and one event handled 24 s after it was sent, nearly all with no slow store lock. The machine had
1.5 GB of 15.7 GB RAM free and paged about 1,000 pages a second. Windows had trimmed the hub to 21 MB
of its 60 MB (110,000 page faults in 80 minutes): each event waited for the hub's own memory to come
back from disk. 364 events in 36 h were not delivered because hooks give up after 1 s.

## Decision
At start-up on Windows the hub enables `SeIncreaseWorkingSetPrivilege` (held, disabled, by ordinary
accounts) and calls `SetProcessWorkingSetSizeEx` with a hard minimum of 96 MB and a soft maximum
(`ronda.resident`). Windows then does not trim the hub below 96 MB. If any step fails, the hub logs
why and runs as before. Nothing changes on macOS and Linux.

Also: Ronda's processes set the `httpx` and `httpcore` loggers to WARNING (`ronda.logs`); httpx had
written one line per OpenBot poll, 16,845 lines in 1.5 h.

## Consequences
- The hub holds up to 96 MB of RAM even when idle; other programs page a little more instead.
- Hooks are new processes and are not covered: under heavy paging their own start-up can still be
  slow. The next dogfooding run shows whether "not delivered" drops to near 0.
- Alternatives not taken: `VirtualLock` (needs the whole heap to be locked piece by piece), a higher
  hook timeout (the hard limit is 2 s and stalls reached 5.6 s).
