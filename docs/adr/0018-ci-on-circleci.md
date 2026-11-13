# ADR-0018: CI runs on CircleCI; releases stay on GitHub Actions

- Status: Accepted
- Date: 2026-11-13

## Context
The repository's GitHub Actions minutes ran out (private repository, free plan), so pull requests
were merged without a test run. CircleCI's free plan covers the test load.

## Decision
- `.circleci/config.yml` runs two jobs on every push: `python` (`cimg/python:3.12`, `uv sync --locked`,
  `uv build`, pytest through CircleCI's test suites with every paid option off) and `web`
  (`cimg/node:20.20`, `npm ci`, `npm run build`).
- The GitHub Actions test workflow (`ci.yml`) is deleted, so a pull request shows one CI result.
- `release.yml` stays on GitHub Actions. It runs only on version tags, and PyPI trusted publishing
  is set up for a GitHub workflow (docs/release.md). It needs Actions minutes, or a move, before the
  first release.

## Consequences
- CI runs on Linux with Python 3.12 only. Windows, macOS, Python 3.11 and tmux are no longer tested
  in CI (the old matrix covered them); they are tested by hand until jobs are added.
- The first tagged release fails while Actions minutes are used up. This must be settled before beta.
