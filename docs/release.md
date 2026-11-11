# Releasing

## Names (checked 2026-11-11)

| Where | Name | State |
| --- | --- | --- |
| PyPI | `ronda` | available (also `ronda-agents`, `ronda-inbox`) |
| npm | `ronda` | taken (a 2022 server-monitoring app); Ronda does not need npm |
| GitHub org | `ronda`, `ronda-dev`, `rondadev` | taken |
| GitHub org | `rondahq`, `ronda-hq`, `getronda`, `ronda-app`, `ronda-sh` | available |
| Domain | not checked | |

Claim the PyPI name with the first release, before going public.

## Cutting a release

1. Bump `version` in `pyproject.toml` (and `__version__` in `src/ronda/__init__.py`), commit, merge.
2. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`.
3. The `release` workflow builds the web UI into the package, builds the wheel and sdist, checks the
   wheel carries `hub/static`, `hosts.yaml` and `pos/tmux/agents.yaml`, and attaches them to a
   GitHub Release.

## Turning on PyPI publishing (once)

1. On PyPI, add a *pending trusted publisher* for project `ronda`: owner `wingscode123`, repository
   `ronda`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repo: Settings, Environments, create `pypi`; Settings, Variables, add
   `PUBLISH_PYPI = true`.
3. The next tag publishes. Users then install with `pipx install ronda` (or `uv tool install ronda`).

## Installing before PyPI

A plain `pipx install git+https://...` builds from source without the web UI (it is built by the
workflow, not committed). Install the wheel attached to a GitHub Release instead:
`pipx install ./ronda-<version>-py3-none-any.whl`, or from a checkout as in the README.
