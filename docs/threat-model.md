# Threat model

Ronda can approve shell commands and type into agents on the user's behalf. Whoever can drive Ronda
can act roughly like someone at the user's terminal. This document lists what Ronda protects, from
whom, how, and what is left over. Version: M4 (pre-alpha), 2026-11-11.

## What is worth attacking

| Asset | Why it matters |
| --- | --- |
| The ability to approve, deny or reply | Approve runs a command; reply instructs an agent |
| `~/.ronda/token` | Full access to the hub API |
| OpenBot's automation token (read, not stored) | Answer OpenBot approvals |
| Session data: commands, summaries, paths | Can contain secrets and business details |
| Audit log | Proof of who approved what |

## Who might try

1. **A web page** in the user's browser (CSRF, DNS rebinding against `127.0.0.1:7878`).
2. **Another OS user** on the same machine.
3. **Text produced by an agent or a repo** (prompt injection through summaries or commands).
4. **Malware running as the user.** Out of scope: it can already run commands and read every file.

## Boundaries

```
agents --hooks / screen / OpenBot API--> pos (same user) --loopback HTTP + token--> hub (127.0.0.1)
browser --cookie + Origin + Host checks--> hub
```

## Threats and controls

| # | Threat | Controls | Where |
| --- | --- | --- | --- |
| T1 | A web page approves a command | Token on every request; browser uses an HttpOnly SameSite=Strict cookie; state-changing cookie requests and every WebSocket need the hub's own `Origin`; `Host` must be `127.0.0.1:<port>`/`localhost:<port>` (DNS rebinding) | ADR-0007, `hub/auth.py` |
| T2 | Another user reads the token | `~/.ronda/token` mode 600 on POSIX; on Windows the user profile ACL | `hub/auth.py`, doctor |
| T3 | Ronda approves something nobody chose | Never auto-approves. Hooks print a decision only for an explicit action on the exact request id; every failure, timeout or doubt prints nothing and the agent asks in its own prompt | ADR-0003, ADR-0008, `hook.py` |
| T4 | An old or replayed approval lands on a new question | Request ids; an action is delivered once; pending actions expire as soon as the session moves on; the hub refuses actions for requests that are not pending | `hub/api.py`, `store.py` |
| T5 | A dangerous command approved by mistake | Denylist (`rm -rf`, `git push --force`, `sudo`, `curl ... \| sh`, ...) needs a second confirmation in the UI and CLI | `config.DEFAULT_RISKY` |
| T6 | Answer typed into the wrong terminal | tmux/Orca pos check the pane still runs the same agent process/run before sending keys | ADR-0013, ADR-0015 |
| T7 | Secrets leave the machine | Ronda makes no outbound calls: the hub binds to 127.0.0.1 and nothing forwards to the internet; desktop notifications carry no command text | ADR-0003 |
| T9 | Logs leak data | `hook.log` has event names and error types only; `sent.log` has ids and statuses; tokens are never logged | `hook.py`, OpenBot pos |
| T10 | Ronda slows or blocks agents | Hooks async except PermissionRequest (waits, but the agent's own prompt stays usable) and SessionEnd (0.5 s); 2 s watchdog otherwise; hub limits batch and field sizes | ADR-0003, ADR-0008 |

## Residual risks

- **The login link** is a one-time code valid for 10 minutes (`/?login=...`, from `ronda up` or
  `ronda open`); the token itself never appears in a URL. Whoever opens an unspent link first gets a
  session cookie. If a token may have leaked, `ronda token rotate` and restart `ronda up`.
- **Screen-reading pos can be wrong** (ADR-0013): a "question" Ronda detects may not be one. The
  person still decides; the keys sent are the configured ones only.
- **Replies are instructions.** Whoever can reply (inbox, CLI) can steer the agent; Ronda
  treats them as the user's own words.
- **Windows file permissions** rely on the profile ACL, not on mode bits.
- **Same-user malware** is not something Ronda can defend against.

## Reporting

See [SECURITY.md](../SECURITY.md).
