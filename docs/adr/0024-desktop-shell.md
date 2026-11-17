# ADR-0024: Tauri desktop shell attached to the bundled hub

- Status: Accepted
- Date: 2026-11-17

## Context
SeKantor ships as a Windows desktop app for users without Python or uv (design spec 5.3). The hub
stays the Python hub, frozen by PyInstaller into a `sekantor/` folder (`sekantor.exe`,
`sekantor-hub.exe`, `sekantor-hook.exe`). The hub outlives the window: hooks post events whether or
not the office is open, and only "Quit SeKantor" stops it. The app must also work while no hub runs
(first install, after Quit) and while the hub is slow to answer (the owner's laptop pages heavily,
ADR-0019, ADR-0020). Rust, MSVC and the Tauri CLI are not installed on the owner's machine; the shell
is built and tested only in CI.

## Decision
- `desktop/` holds a Tauri 2 shell (`tray-icon` feature, `tauri-plugin-single-instance`), identifier
  `dev.sekantor.app`, an unsigned NSIS installer in per-user mode. The PyInstaller folder is a bundle
  resource (`../../dist/sekantor/` to `sekantor/`).
- The shell holds no product logic. The hub serves the UI; the window loads
  `http://127.0.0.1:<port>/?login=<code>` with a fresh one-time code from `POST /v1/login-code`
  (bearer), so the token never appears in a URL and the window gets the same cookie as a browser
  (ADR-0007). The token is read from `~/.sekantor/token` (or `SEKANTOR_HOME`) on each request and is
  stored nowhere else.
- First run: a bundled local page asks `sekantor.exe setup --json`. When hooks are not `ok` or the
  service is off it shows a status list and a "Connect Claude Code" button that runs
  `setup --apply`. Otherwise it goes straight on. The page is the only local page and it can call
  only the app's three commands (`status`, `connect`, `open_office`); the hub page is a remote URL and
  gets no IPC. CSP allows `'self'` and `http://127.0.0.1:*` only.
- Attaching: if `GET /v1/health` does not answer, start `sekantor-hub.exe up --no-open --log-file
  <home>/hub.log` detached with no window, then poll health every 500 ms for up to 30 s. Each HTTP
  call has a 5 s timeout and 3 tries 1 s apart when it times out or gets a 5xx; a refused connection
  (nothing listening) or a 4xx is not retried. `up` ignores `SEKANTOR_PORT`, so a non-default port is
  passed as `--port`.
- Closing the window hides it. The tray menu has "Open SeKantor" and "Quit SeKantor"; Quit sends
  `POST /v1/shutdown` (bearer) and then exits the app.
- HTTP uses `ureq` 2 without TLS or proxy support: every request goes to 127.0.0.1. Child processes
  run with `CREATE_NO_WINDOW`.
- Logic lives in `hub.rs` and `setup.rs` with no Tauri types, so `cargo test` covers it with fake
  launchers, health checks and sleeps; `main.rs` only wires commands, the tray and window events.
- Icons are generated in CI from `brand/logo/icon-512.png` (`npm run icons` in `desktop/`) into
  `desktop/src-tauri/icons/`, which is not committed.

## Consequences
- The UI stays in the hub, so a later Rust hub can replace the sidecar without touching the shell.
- The shell cannot be compiled or run on the owner's machine; compile errors surface in CI first.
- `tauri-build` needs the icons and `dist/sekantor/` to exist before any `cargo` command, including
  `cargo test`, so CI generates the icons and builds the PyInstaller folder first.
- If Quit cannot reach the hub (it does not answer after the retries), the app still exits and the
  hub keeps running until the next Quit or sign-out.
- A second hub launched while the service is starting one finds the port taken and exits; the
  window attaches to whichever answers.
