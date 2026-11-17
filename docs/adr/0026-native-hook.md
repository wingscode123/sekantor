# ADR-0026: A native forwarder is the Claude Code hook; the hub translates

- Status: Accepted
- Date: 2026-11-17

## Context
SentinelOne on the owner's corporate laptop flags every run of the unsigned PyInstaller
`sekantor-hook.exe` as "Suspicious file executed". The hook runs on every agent action, so the alerts
never stop, and each run also unpacks a Python runtime. Code signing comes later. The spec (section 8,
"Hooks") already allowed the hook to become a small native forwarder that posts the raw payload.

## Decision
- `hook/` is a Rust crate, `sekantor-hook`: std only plus `serde_json`, no async, no HTTP crate. The
  release profile optimises for size (`opt-level = "z"`, LTO, stripped, `panic = "abort"`).
- It reads the hook payload on stdin (at most 4 MiB, else nothing is sent), and when it is a JSON
  object POSTs `{"v": 1, "id", "ts", "payload", "env"}` to `POST /v1/hooks/claude` on 127.0.0.1 over a
  plain `TcpStream`, HTTP/1.1, `Connection: close`, bearer token from `<home>/token`. The hub applies
  `ignore_cwd`, translates, fingerprints and sends the deep host follow-up, as the Python hook did.
- `id` keeps the `event_id` format (16 hex of nanoseconds + 8 random hex); `ts` is ISO 8601 UTC. The
  random part comes from `/dev/urandom` or, on Windows, std's randomly seeded `RandomState`.
- `env` holds only the names listed in `<home>/hook-env.txt` (the hub writes every `env:` name in its
  host rules) plus `CLAUDE_PID`, matched case-insensitively on Windows. Nothing else in the
  environment, such as API keys, leaves the process.
- The failure rules of ADR-0021 stay: a watchdog thread exits 0 after 2.0 s; connect, write and read
  share one deadline of 1.0 s (1.5 s for SessionEnd), cut so the request ends at least 150 ms before
  the watchdog (no time left: no request, the failure is logged at once); reading stops once the head
  and `Content-Length` bytes are in. The process never prints and always exits 0, a panic included.
- The `sent.log` line is written after the reply, with the `ts` taken before sending. It is left out
  only when the hub answered 2xx with a JSON body holding `"stored": false` (it dropped the event on
  purpose, e.g. `ignore_cwd`); a timeout, refusal, non-2xx or unclear body still writes it, next to the
  `hook.log` line, so `sekantor stats` counts it as lost while the hub was down, as before.
- `sent.log` (`<ts> <id> claude:<session_id> <hook_event_name>`, rotated past 2 MiB) and `hook.log`
  (`<local %Y-%m-%dT%H:%M:%S> <hook_event_name>: hub unreachable (<Err>) <id>`, rotated past 256 KiB)
  keep the Python hook's formats; `<Err>` is the Python exception name for the same failure
  (`TimeoutError`, `ConnectionRefusedError`, `RuntimeError` for a non-2xx answer), so `sekantor stats`
  reads lines from both hooks. Local time comes from `GetLocalTime` on Windows and `localtime_r` on
  64-bit Unix; other targets fall back to UTC.
- The Python hook stays for source installs; the hub accepts both.
- The crate compiles and its tests run only on CircleCI (ADR-0025); no `Cargo.lock` is committed.

## Consequences
- The hook is one small native exe with no interpreter inside, so it starts in milliseconds and is a
  much smaller target for reputation-based scanners. It is still unsigned until signing lands.
- Hook behaviour now lives in the hub: a translation fix needs a hub restart, not a hook reinstall.
- `sent.log` lists what the hub stored or might have stored; payloads the hub reports as dropped are
  left out, as the Python hook left out events it did not build. If the process is killed mid-request
  (only possible past the 2 s watchdog) the event has no `sent.log` line.
- No one can build or test the hook locally without installing Rust; CI is the only check.
