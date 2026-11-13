"""Display names for agents, host apps and statuses: the one copy the hub, notifications and relays use."""

SOURCES = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "opencode", "gemini": "Gemini", "aider": "Aider"}
HOSTS = {
    "orca": "Orca", "openbot": "OpenBot", "claude-desktop": "Claude desktop", "vscode": "VS Code", "cursor": "Cursor",
    "jetbrains": "JetBrains", "tmux": "tmux", "windows-terminal": "Windows Terminal", "iterm": "iTerm2",
    "apple-terminal": "Terminal.app", "wezterm": "WezTerm", "ghostty": "Ghostty", "kitty": "kitty", "terminal": "Terminal",
}
TITLES = {"waiting_approval": "Approval needed", "waiting_input": "Waiting for you", "error": "Agent error",
          "running": "Running", "done": "Done", "ended": "Ended"}


def source(source_id: str) -> str:
    return SOURCES.get(source_id, source_id)


def host(app: str) -> str:
    return HOSTS.get(app, app)
