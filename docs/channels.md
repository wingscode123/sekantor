# Channels: phone notifications, Telegram, webhooks, tmux

All of these are optional. `ronda up` starts the ones that are set up, each as its own process; the
hub itself never talks to the internet (ADR-0011). Check with `uv run ronda doctor`.

## ntfy (phone notifications, one way)

1. Install the official **ntfy** app (developer Philipp C. Heckel; server `https://ntfy.sh`).
2. Subscribe to a long random topic, for example `ronda-<random>`. The topic name is the secret.
3. Add to `~/.ronda/config.toml`:

   ```toml
   [[webhooks]]
   url = "https://ntfy.sh/ronda-<random>"
   format = "ntfy"
   statuses = ["waiting_approval", "waiting_input", "error"]
   ```
4. Restart `ronda up`, then `uv run ronda relay --test`.

Approve and reply still happen on the computer (inbox or `ronda approve|deny|reply`).

## Telegram (two way)

1. Create a bot with **@BotFather** and copy its token.
2. `uv run ronda pair telegram`: paste the token (not shown), then send `/pair <code>` to the bot.
3. Restart `ronda up`.

You get a message when an agent needs you, with Approve/Deny buttons. Reply to a message to answer
an agent that finished its turn. `/status` lists who needs you. Only the paired chat is answered.
Risky commands show Deny only. `uv run ronda unpair telegram` forgets the bot.

## Quiet hours and snooze

Add `quiet_hours = "22:00-07:00"` to `~/.ronda/config.toml` (local time) for no desktop, Telegram or
webhook notifications in that window. To mute one agent for a while, use Snooze on its card (30 min,
2 h, 8 h, or until you unmute it) or `uv run ronda snooze <session> --minutes 120`.

## Other webhooks

`format = "json"` (default, `{"type": "session.status", ...}`), `"text"`, `"slack"` (incoming
webhook), or `"ntfy"`. Add `secret = "..."` to get an `X-Ronda-Signature: sha256=<hmac>` header.
Text is redacted (keys, tokens, passwords) before it leaves the machine.

## tmux pos

On Linux/macOS with tmux installed, `ronda up` also watches codex, opencode, gemini and aider in tmux
panes. Their state is read from the screen with the patterns in `src/ronda/pos/tmux/agents.yaml`
(best guesses: please send corrections with a `tmux capture-pane -p` sample). Claude Code panes are
skipped because its hooks already report them.
