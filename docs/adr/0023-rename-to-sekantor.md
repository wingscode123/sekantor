# ADR-0023: Rename Ronda to SeKantor

- Status: Accepted
- Date: 2026-11-16

## Context
The product watches agents and no longer answers for them (ADR-0021). The new direction is a pixel
office where each agent has a desk, and the name Ronda (a night watch round) no longer fits. The owner
approved the new name, SeKantor, on 2026-11-16. The owner already runs a Ronda hub as a service with
hooks in `~/.claude/settings.json`, so the rename must not lose their token, settings or history and
must not leave two hubs or two sets of hooks.

## Decision
- Package, CLI and hook are `sekantor` and `sekantor-hook`; env vars are `SEKANTOR_*`; the home is
  `~/.sekantor` and the database `sekantor.db`. "SeKantor" is the spelling in prose and UI.
- `config.migrate_home(old, new)` runs first in `sekantor up`, `sekantor install claude` and
  `sekantor service install`. When `~/.sekantor` does not exist and `~/.ronda` does, it copies the
  token (mode 600), `config.toml`, `hosts.cache.json` and the database (SQLite `backup`, safe while an
  old hub writes). It never touches `~/.ronda` and never overwrites anything in `~/.sekantor`. It is
  skipped when `SEKANTOR_HOME` is set.
- `install.is_ours` matches both `sekantor-hook` and `ronda-hook`, so installing replaces the old
  handlers instead of adding a second set.
- The service is `SeKantor hub` / `dev.sekantor.hub` / `sekantor.service`. `service install` first
  removes the old `Ronda hub` / `dev.ronda.hub` / `ronda.service` (`Plan.cleanup`, errors ignored).
- The old `RONDA_*` env vars are not read.

## Upgrade steps
Stop the Ronda hub, `git pull`, `uv sync`, `uv run sekantor install claude --global`,
`uv run sekantor service install`, `uv run sekantor doctor`. Until the hooks are reinstalled the old
`ronda-hook` handlers point at a removed executable and fail silently; hooks never block an agent.

## Consequences
- The old `~/.ronda` stays on disk; the owner deletes it when satisfied.
- ADRs, the PRD, the improvement log and the spike notes keep the name Ronda as history.
