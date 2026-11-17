# ADR-0025: PyInstaller folder and the Windows installer build on CircleCI

- Status: Accepted
- Date: 2026-11-17

## Context
The desktop app (ADR-0024) bundles the Python hub for users without Python. Rust, MSVC and PyInstaller
must not be installed on the owner's machine, so the installer is built and checked only in CI.
Uninstalling must leave no hooks in `~/.claude/settings.json` and no login task behind.

## Decision
- `packaging/sekantor.spec` builds one PyInstaller folder, `dist/sekantor/`, with three exes sharing one
  runtime: `sekantor.exe` (console), `sekantor-hub.exe` (windowed, so the app and the login task start
  the hub with no console window) and `sekantor-hook.exe` (console). Data files keep the package
  layout (`sekantor/hub/static`, `sekantor/hosts.yaml`, `sekantor/pos/tmux/agents.yaml`), so code that
  reads them next to its module works frozen. A folder, not one-file: no unpacking on every hook call.
- The windowed hub has no stdout or stderr; `packaging/entry_hub.py` points them at the null device
  before the CLI loads (uvicorn's formatter calls `sys.stderr.isatty()`).
- `pyinstaller` lives in the `packaging` dependency group; only CI runs `uv sync --group packaging`.
- The NSIS pre-uninstall hook (`desktop/src-tauri/windows/hooks.nsh`) runs, from the installed folder,
  `sekantor.exe stop` (so the hub's files can be deleted), `uninstall claude --global` and
  `service uninstall`, ignoring errors.
- CircleCI job `desktop-windows` (main, `desktop-*` branches, or pipeline parameter `desktop=true`):
  web build, PyInstaller, `packaging/smoke.py` (temporary home, port 7899), icons, `cargo test`,
  `tauri build`, then `packaging/installer_check.py`: silent install, `setup --apply`, silent
  uninstall, and a check that no hooks, login task or `sekantor/` folder are left.

## Consequences
- Every build checks the frozen exes and the uninstall path end to end on a clean VM; a local build is
  possible in a worktree but never needed.
- Two Rust builds per run (`cargo test` in debug, `tauri build` in release) make the job slow; the
  cargo registry and `target/` are cached on `Cargo.toml`.
- If Tauri runs the old uninstaller during an upgrade, the hook removes the hooks and the login task;
  the new app's first run puts them back (it sees `hooks: missing`).
