# Threat model

Ronda can approve shell commands and type into agents on the user's behalf. Whoever can drive Ronda
can act roughly like someone at the user's terminal. This document lists what Ronda protects, from
whom, how, and what is left over. Version: M4 (pre-alpha), 2026-11-11.

## What is worth attacking

| Asset | Why it matters |
| --- | --- |
| The ability to approve, deny or reply | Approve runs a command; reply instructs an agent |
| `~/.ronda/token` | Full access to the hub API |
| `~/.ronda/telegram.json` | Bot token + the allowed chat: approve from a phone |
| OpenBot's automation token (read, not stored) | Answer OpenBot approvals |
| Session data: commands, summaries, paths | Can contain secrets and business details |
| Audit log | Proof of who approved what |

## Who might try

1. **A web page** in the user's browser (CSRF, DNS rebinding against `127.0.0.1:7878`).
2. **Another OS user** on the same machine.
3. **Someone with the user's Telegram account**, or who learns an ntfy topic or webhook URL.
4. **Text produced by an agent or a repo** (prompt injection through summaries or commands).
5. **Malware running as the user.** Out of scope: it can already run commands and read every file.

## Boundaries

```
agents --hooks / screen / OpenBot API--> pos (same user) --loopback HTTP + token--> hub (127.0.0.1)
browser --cookie + Origin + Host checks--> hub
relay (same user) --loopback--> hub ;  relay --HTTPS--> Telegram, webhooks (the only internet traffic)
```

## Threats and controls

| # | Threat | Controls | Where |
| --- | --- | --- | --- |
| T1 | A web page approves a command | Token on every request; browser uses an HttpOnly SameSite=Strict cookie; state-changing cookie requests and every WebSocket need the hub's own `Origin`; `Host` must be `127.0.0.1:<port>`/`localhost:<port>` (DNS rebinding) | ADR-0007, `hub/auth.py` |
| T2 | Another user reads the token | `~/.ronda/token` and `telegram.json` mode 600 on POSIX; on Windows the user profile ACL | `hub/auth.py`, doctor |
| T3 | Ronda approves something nobody chose | Never auto-approves. Hooks print a decision only for an explicit action on the exact request id; every failure, timeout or doubt prints nothing and the agent asks in its own prompt | ADR-0003, ADR-0008, `hook.py` |
| T4 | An old or replayed approval lands on a new question | Request ids; an action is delivered once; pending actions expire as soon as the session moves on; the hub refuses actions for requests that are not pending | `hub/api.py`, `store.py` |
| T5 | A dangerous command approved by mistake | Denylist (`rm -rf`, `git push --force`, `sudo`, `curl ... \| sh`, ...) needs a second confirmation in the UI and CLI; never from Telegram (button hidden and refused by the hub) | `config.DEFAULT_RISKY`, ADR-0012 |
| T6 | Answer typed into the wrong terminal | tmux/Orca pos check the pane still runs the same agent process/run before sending keys | ADR-0013, ADR-0015 |
| T7 | Secrets leave the machine | Hub makes no outbound calls; only the relay does. Text is redacted (keys, tokens, passwords, bearer headers, URL credentials, known key formats) before Telegram or a webhook; desktop notifications carry no command text | ADR-0011, `relay/redact.py` |
| T8 | A stranger talks to the Telegram bot | Pairing with a one-time code (5 min); only the paired chat id is answered; callback data is a random key, not a session id | ADR-0012 |
| T9 | Logs leak data | `hook.log` has event names and error types only; `sent.log` has ids and statuses; tokens are never logged | `hook.py`, relay, OpenBot pos |
| T10 | Ronda slows or blocks agents | Hooks async except PermissionRequest (waits, but the agent's own prompt stays usable) and SessionEnd (0.5 s); 2 s watchdog otherwise; hub limits batch and field sizes | ADR-0003, ADR-0008 |

## Residual risks

- **The login link** (`/?token=...`) shows the token in the terminal and may stay in browser
  history. Anyone with that link has full access until the token changes. Planned: `ronda token
  rotate` and a short-lived login code.
- **A taken-over Telegram account** can approve non-risky commands and send replies. Unpair with
  `ronda unpair telegram`; consider keeping approvals local.
- **ntfy topics and webhook URLs are bearer secrets.** Anyone who knows the topic reads the
  (redacted) notifications. Self-host ntfy for stronger privacy.
- **Redaction is pattern-based.** A secret in an unusual shape can pass through.
- **Screen-reading pos can be wrong** (ADR-0013): a "question" Ronda detects may not be one. The
  person still decides; the keys sent are the configured ones only.
- **Replies are instructions.** Whoever can reply (inbox, CLI, Telegram) can steer the agent; Ronda
  treats them as the user's own words.
- **Windows file permissions** rely on the profile ACL, not on mode bits.
- **Same-user malware** is not something Ronda can defend against.

## Reporting

See [SECURITY.md](../SECURITY.md).
