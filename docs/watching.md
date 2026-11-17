# Quiet hours, snooze and tmux

Check your setup with `uv run sekantor doctor`.

## Quiet hours and snooze

Add `quiet_hours = "22:00-07:00"` to `~/.sekantor/config.toml` (local time) for no desktop notifications
in that window. To mute one agent for a while, use Snooze on its card (30 min, 2 h, 8 h, or until you
unmute it) or `uv run sekantor snooze <session> --minutes 120`.

## tmux pos

On Linux/macOS with tmux installed, `sekantor up` also watches codex, opencode, gemini and aider in tmux
panes. Their state is read from the screen with the patterns in `src/sekantor/pos/tmux/agents.yaml`
(best guesses: please send corrections with a `tmux capture-pane -p` sample). Claude Code panes are
skipped because its hooks already report them.
