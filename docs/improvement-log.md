# Improvement log: the pstack audit and what followed

From 12 to 13 November 2026 the repository went through a read-only code-quality audit with the
[pstack](https://github.com/cursor/plugins/tree/main/pstack) plugin for Claude Code, then three
cleanup PRs, a move of CI to CircleCI, and a dogfooding round. This page records what changed and
why, and what is still open.

## Result in short

The core code is about the same size (Python and web source: 389 lines added, 404 removed), with
fewer duplicate rules and four correctness bugs fixed. Tests went from 232 passing (plus one flaky
Windows failure) to 255 passing. CI runs on CircleCI. The hub now logs where the time goes when it is
slow. Everything is on `main` in 28 commits.

## 1. Audit (read-only)

- pstack's `poteto-mode` Investigation playbook, with three parallel explorers: hub and web, pos and
  relay, CLI/config/tooling. Each explorer claim was checked against the code before it was reported.
- Finding: a lean codebase. Every dependency is used, and the complex parts (the hook's raw socket
  client, auth middleware, status fold, store locking) are justified by ADRs and tests. The problems
  were small and scattered, plus a few correctness bugs hidden behind swallowed errors.

## 2. Cleanup PRs

| PR | What |
| --- | --- |
| [#8](https://github.com/wingscode123/ronda/pull/8) | Deleted dead code and stray files: `halo.txt`, a leaked shell heredoc (with a local path) at the end of `docs/writing-a-pos.md`, unread fields and helpers, unused imports, the `web/dist` and `RONDA_WEB_DIST` lookups, duplicated dev dependencies. |
| [#9](https://github.com/wingscode123/ronda/pull/9) | One copy of each rule. Display names (`ronda.labels`) had drifted between toasts, Telegram and the inbox. Also one copy each of the hook's paths, the polling pos start-up (`ronda.pos.hub`), the `config.toml` read, the CLI's hub-down handling and the web fetch helper. |
| [#10](https://github.com/wingscode123/ronda/pull/10) | Bugs, each with a failing test first: a tmux/Orca timeout ended every session, the sweep published from a worker thread so a session's end could miss the inbox, a snooze overwrote an event stored meanwhile, `config.toml` problems were silent and one bad value reset every setting, and CLI messages misled. The unused `Pos` Protocol (`pos/base.py`) was deleted and the docs now show the HTTP contract every pos uses. |
| [#13](https://github.com/wingscode123/ronda/pull/13) | Brought #9 and #10 to `main`: they had merged into their stacked base branches. |

## 3. CI on CircleCI

GitHub Actions ran out of minutes, so CI moved.

- [#12](https://github.com/wingscode123/ronda/pull/12): `.circleci/config.yml` with a Python job
  (`cimg/python:3.12`, uv, `uv build`, pytest) and a web job (`cimg/node:20.20`, `npm run build`).
  Tests run through CircleCI Smarter Testing (`.circleci/test-suites.yml`) with every paid option off.
  `circleci testsuite doctor` passes in CI.
- [#16](https://github.com/wingscode123/ronda/pull/16): removed the GitHub Actions test workflow.
  `release.yml` stays; it runs only on version tags.

## 4. Dogfooding and the slow hub

`ronda stats --since 24h` showed 3,740 of 3,745 events stored, but 770 hook "hub unreachable" errors.

- All were `TimeoutError`. On Windows a closed port also times out after 1 s, so the error alone does
  not tell a down hub from a slow one.
- `events.received_at` minus `ts` settled it. The events did arrive, but 13 s to 163 s late, in two
  bursts of heavy agent activity. The hub was alive and stalled.
- A burst of 32 parallel hook posts against a copy of the real database stayed under 0.2 s, so the
  cause shows only under real machine load. It is not fixed yet: the next step waits for data.
- [#14](https://github.com/wingscode123/ronda/pull/14): the hub logs, with timestamps, a blocked event
  loop, the store-lock wait and hold time, and events that arrive late. Each logs only past 1 s, the
  hook's own timeout.
- [#15](https://github.com/wingscode123/ronda/pull/15): `hub.log` had reached 11 MB of "OpenBot not
  reachable" lines. The OpenBot pos now logs only changes, and `ronda up --log-file` rotates a log
  over 5 MB.

## 5. Lessons

- In a PR stack, retarget the next PR to `main` before merging it, or delete each merged branch
  first. Otherwise it merges into the old base branch.
- `Stop-ScheduledTask` returns before the hub has exited. Wait until nothing listens on port 7878
  before `Start-ScheduledTask`, or the new hub sees the port busy and exits.
- Never run `uv sync` while the hub runs from the same `.venv`: it tries to replace `ronda-hook.exe`,
  which hooks may hold open.

## 6. Still open

1. Fix the hub stalls once `hub.log` shows "event loop was blocked", "waited ... for the store lock"
   or "sent N s ago" during one.
2. Decide on the unused `stop` and `open` capabilities, the pre-M2 hook install compatibility,
   `scripts/spike/` and `.hallmark/`.
3. Releasing before the beta (25 January 2027): GitHub Actions minutes for `release.yml`, or move it
   to CircleCI.
4. Optional CI jobs: Windows, Python 3.11, tmux.
