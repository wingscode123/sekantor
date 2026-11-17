# Threat model

SeKantor watches coding agents and reports their status. It approves nothing and sends nothing to agents
(ADR-0021): there is no path from the hub back to an agent. What it can still do is show session data,
mute or snooze sessions, and bring the app a session runs in to the front on this computer. This
document lists what SeKantor protects, from whom, how, and what is left over.

## What is worth attacking

| Asset | Why it matters |
| --- | --- |
| `~/.sekantor/token` | Full access to the hub API (read sessions, mute, snooze, open an app) |
| OpenBot's automation token (read, never stored) | Lets the OpenBot pos list agents |
| Session data: summaries, paths, tool names | Can contain secrets and business details |

## Who might try

1. **A web page** in the user's browser (CSRF, DNS rebinding against `127.0.0.1:7878`).
2. **Another OS user** on the same machine.
3. **Text produced by an agent or a repo** (prompt injection through summaries).
4. **Malware running as the user.** Out of scope: it can already run commands and read every file.

## Boundaries

```
agents --hooks / screen / OpenBot API--> pos (same user) --loopback HTTP + token--> hub (127.0.0.1)
browser --cookie + Origin + Host checks--> hub
```

Nothing flows from the hub to an agent.

## Threats and controls

| # | Threat | Controls | Where |
| --- | --- | --- | --- |
| T1 | A web page reads or changes hub state | Token on every request; browser uses an HttpOnly SameSite=Strict cookie; state-changing cookie requests and every WebSocket need the hub's own `Origin`; `Host` must be `127.0.0.1:<port>`/`localhost:<port>` (DNS rebinding) | ADR-0007, `hub/auth.py` |
| T2 | Another user reads the token | `~/.sekantor/token` mode 600 on POSIX; on Windows the user profile ACL | `hub/auth.py`, doctor |
| T3 | Secrets leave the machine | SeKantor makes no outbound calls: the hub binds to 127.0.0.1 and nothing forwards to the internet; desktop notifications carry no command text | ADR-0003 |
| T4 | Logs leak data | `hook.log` has event names and error types only; tokens are never logged | `hook.py`, OpenBot pos |
| T5 | SeKantor slows or blocks agents | Every hook runs async in exec form (no shell) except SessionEnd, which is synchronous with a 5 s hook timeout and a 1.5 s HTTP timeout; a watchdog ends a hung hook; the hub limits batch and field sizes | ADR-0003, ADR-0021 |

### Removed with the answer path

The earlier threats about approving or replying are gone because the controls and the feature are gone
(ADR-0021): approving something nobody chose, replayed approvals, a risky-command denylist, and answers
typed into the wrong terminal. With no answer path there is no request id to replay, no keys sent to a
pane, and no decision printed by a hook. A SeKantor hook never prints a decision, so the agent always
shows its own prompt.

## Residual risks

- **The login link** is a one-time code valid for 10 minutes (`/?login=...`, from `sekantor up` or
  `sekantor open`); the token itself never appears in a URL. Whoever opens an unspent link first gets a
  session cookie. If a token may have leaked, `sekantor token rotate` and restart `sekantor up`.
- **Screen-reading pos can be wrong** (ADR-0013): a "waiting" status SeKantor detects may not be one.
  The status is a hint; nothing is sent to the pane.
- **Agent-written text is shown as is.** Summaries come from the agent or repo and are rendered as text,
  never as instructions to SeKantor.
- **Windows file permissions** rely on the profile ACL, not on mode bits.
- **Same-user malware** is not something SeKantor can defend against.

## Reporting

See [SECURITY.md](../SECURITY.md).
