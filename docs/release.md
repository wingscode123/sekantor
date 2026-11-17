# Releasing

## Names (checked 2026-11-11)

| Where | Name | State |
| --- | --- | --- |
| PyPI | `sekantor` | available (also `sekantor-agents`, `sekantor-inbox`) |
| npm | `sekantor` | taken (a 2022 server-monitoring app); SeKantor does not need npm |
| GitHub org | `sekantor`, `sekantor-dev`, `sekantordev` | taken |
| GitHub org | `sekantorhq`, `sekantor-hq`, `getsekantor`, `sekantor-app`, `sekantor-sh` | available |
| Domain | not checked | |

Claim the PyPI name with the first release, before going public.

## Cutting a release

1. Bump `version` in `pyproject.toml` (and `__version__` in `src/sekantor/__init__.py`), commit, merge.
2. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`.
3. The `release` workflow builds the web UI into the package, builds the wheel and sdist, checks the
   wheel carries `hub/static`, `hosts.yaml` and `pos/tmux/agents.yaml`, and attaches them to a
   GitHub Release.

## Turning on PyPI publishing (once)

1. On PyPI, add a *pending trusted publisher* for project `sekantor`: owner `wingscode123`, repository
   `sekantor`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repo: Settings, Environments, create `pypi`; Settings, Variables, add
   `PUBLISH_PYPI = true`.
3. The next tag publishes. Users then install with `pipx install sekantor` (or `uv tool install sekantor`).

## Installing before PyPI

A plain `pipx install git+https://...` builds from source without the web UI (it is built by the
workflow, not committed). Install the wheel attached to a GitHub Release instead:
`pipx install ./sekantor-<version>-py3-none-any.whl`, or from a checkout as in the README.
