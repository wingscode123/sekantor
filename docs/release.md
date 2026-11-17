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

## Desktop installer (Windows)

The app (Tauri shell plus the hub frozen by PyInstaller, ADR-0024 and ADR-0025) is built only on
CircleCI, by the `desktop-windows` job. It runs on `main` and on branches named `desktop-*`; on any
other branch, trigger a pipeline with the parameter `desktop` set to `true`.

1. Open the pipeline in CircleCI, job `desktop-windows`, tab Artifacts.
2. Download `installer/SeKantor_<version>_x64-setup.exe`. It is unsigned: Windows SmartScreen asks
   for "More info", then "Run anyway".
3. The installer puts the app in `%LOCALAPPDATA%\SeKantor` (no admin rights). First run offers
   "Connect Claude Code", which installs the hooks globally and the login task, pointing at
   `%LOCALAPPDATA%\SeKantor\sekantor\`. A source install's hooks and task are replaced, not doubled.
   If a source install's hub is running (task "SeKantor hub"), the first run ends that task, waits for
   port 7878 and starts the app's hub from the new task. If the result is `restart_needed` (a hub
   started by hand, or one that would not let go of the port), sign out and in once.
4. Check it with `"%LOCALAPPDATA%\SeKantor\sekantor\sekantor.exe" doctor`.

Uninstalling (Settings, Apps) stops the hub and removes the hooks and the login task first. `~/.sekantor`
(token, events, logs) stays. Upgrading or uninstalling while agents run can hit a locked
`sekantor-hook.exe` (a running hook holds it open): close the agents, or retry.

The job also stores `logs/` (PyInstaller, cargo test, tauri build and installer check output, the
smoke test's temporary home without its token) for debugging a failed run.

To build the PyInstaller folder by hand, in a worktree (never in a checkout whose `.venv` runs your hub):
`(cd web && npm ci && npm run build)`, `uv sync --group packaging`,
`uv run pyinstaller packaging/sekantor.spec --distpath dist --workpath build/pyi`, then
`uv run python packaging/smoke.py dist/sekantor`.
