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
  the hub with no console window) and `sekantor-hook.exe` (console; replaced by a native exe, see the
  2026-11-17 note below). Data files keep the package
  layout (`sekantor/hub/static`, `sekantor/hosts.yaml`, `sekantor/pos/tmux/agents.yaml`), so code that
  reads them next to its module works frozen. A folder, not one-file: no unpacking on every hook call.
- The windowed hub has no stdout or stderr; `packaging/entry_hub.py` points them at the null device
  before the CLI loads (uvicorn's formatter calls `sys.stderr.isatty()`).
- `pyinstaller` lives in the `packaging` dependency group; only CI runs `uv sync --group packaging`.
- NSIS hooks (`desktop/src-tauri/windows/hooks.nsh`), errors ignored:
  - pre-install, when a previous install exists: `sekantor.exe stop --wait`, so an upgrade does not
    overwrite the files of a running hub;
  - pre-uninstall: `stop --wait`, then, unless Tauri's `$UpdateMode` is 1 (uninstaller started with
    `/UPDATE`), `uninstall claude --global` and `service uninstall`.
  `stop --wait` returns once the port is free and no process from the frozen folder is left (up to
  20 s); plain `stop` returns when the hub accepts the request, while it still holds its files.
- CircleCI job `desktop-windows` (main, `desktop-*` branches, or pipeline parameter `desktop=true`):
  web build, PyInstaller, the native hook (`hook/`), `packaging/smoke.py` (temporary home, port
  7899), icons, `cargo test`,
  `tauri build`, then `packaging/installer_check.py`: silent install, `setup --apply`, silent
  uninstall, and a check that no hooks, login task or `sekantor/` folder are left.

## Consequences
- Every build checks the frozen exes and the uninstall path end to end on a clean VM; a local build is
  possible in a worktree but never needed.
- Two Rust builds per run (`cargo test` in debug, `tauri build` in release) make the job slow. Only
  the cargo registry is cached (on `Cargo.toml`; no `Cargo.lock` is committed because nothing outside
  CI has a Rust toolchain); `target/` is too large to cache usefully.
- Upgrades: Tauri's installer only passes `/UPDATE` to the old uninstaller in its own update mode, and
  in that mode it skips uninstalling altogether. A GUI upgrade where the user picks
  "uninstall before installing" runs the old uninstaller without `/UPDATE`, so the hooks and the login
  task are removed: after such an upgrade the user must open the app and click "Connect Claude Code"
  again (first run sees `hooks: missing`). Hooks posting meanwhile fail silently.

## Note (2026-11-17): the hook is native
ADR-0026 replaced the PyInstaller `sekantor-hook.exe` with the Rust forwarder in `hook/`. The spec
now builds only `sekantor.exe` and `sekantor-hub.exe`; the Python hook module stays for source
installs. In `desktop-windows`, right after PyInstaller, `cargo test` and `cargo build --release` run
in `hook/` and `hook/target/release/sekantor-hook.exe` is copied into `dist/sekantor/`, so the smoke
test and `tauri build` see the same three exes as before. The registry cache key covers both
`desktop/src-tauri/Cargo.toml` and `hook/Cargo.toml`. `smoke.py` now checks the forwarder against the
smoke hub (a `Bash` PreToolUse is stored with `activity.kind == "run"`, an `ignore_cwd` payload adds no
`sent.log` line) and without one (exit 0 in under 3 s, no output, one "hub unreachable" line in
`hook.log`); without the exe it skips those checks locally and fails on CI. `installer_check.py` checks that
every SeKantor hook in `settings.json` points at `<install>/sekantor/sekantor-hook.exe`.
