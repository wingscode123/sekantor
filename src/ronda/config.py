"""Paths and defaults. Everything lives in ~/.ronda unless RONDA_HOME says otherwise."""

from __future__ import annotations

import os
from pathlib import Path

HOST = "127.0.0.1"  # never configurable: the hub binds to loopback only
DEFAULT_PORT = 7878


def home() -> Path:
    return Path(os.environ.get("RONDA_HOME") or Path.home() / ".ronda")


def token_path() -> Path:
    return home() / "token"


def db_path() -> Path:
    return home() / "ronda.db"


def hook_log_path() -> Path:
    return home() / "hook.log"


def port() -> int:
    try:
        return int(os.environ.get("RONDA_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def hub_url() -> str:
    return os.environ.get("RONDA_URL") or f"http://{HOST}:{port()}"


# --- settings: ~/.ronda/config.toml (all optional) ----------------------------

DEFAULT_RISKY = [
    r"\brm\s+(-\S*\s+)*-\S*[rRf]",            # rm -rf, rm -r, rm -f
    r"\bgit\s+push\b.*(--force|\s-f\b)",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-\S*f",
    r"\b(drop|truncate)\s+(table|database|schema)\b",
    r"\bmkfs\b|\bdd\s+if=|\bformat\s+[a-z]:",
    r"\bchmod\s+-R\s+777\b",
    r"\bRemove-Item\b.*-Recurse",
    r"\b(shutdown|reboot)\b",
    r"\bsudo\b",
    r"curl[^|]*\|\s*(ba|z)?sh\b",
]


# Claude Code entrypoints where a reply through an asyncRewake Stop hook was verified to wake the agent
# (docs/spike/m2-actions.md): a terminal, and an Orca chat (Agent SDK). Others can be added in config.toml.
DEFAULT_REPLY_ENTRYPOINTS = ["cli", "sdk-ts"]


class Settings:
    def __init__(self, approval_wait_s: int = 600, reply_wait_s: int = 1800, notify: bool = True,
                 risky: list[str] | None = None, reply_entrypoints: list[str] | None = None):
        self.approval_wait_s = max(0, min(int(approval_wait_s), 3600))
        self.reply_wait_s = max(0, min(int(reply_wait_s), 86400))
        self.notify = bool(notify)
        self.risky = list(risky) if risky is not None else list(DEFAULT_RISKY)
        self.reply_entrypoints = [str(e) for e in reply_entrypoints] if reply_entrypoints is not None             else list(DEFAULT_REPLY_ENTRYPOINTS)


def config_path(base: Path | None = None) -> Path:
    return (base or home()) / "config.toml"


def settings(base: Path | None = None) -> Settings:
    """Read config.toml; a missing or broken file gives the defaults."""
    import tomllib

    try:
        with open(config_path(base), "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return Settings()
    try:
        return Settings(
            approval_wait_s=data.get("approval_wait", 600),
            reply_wait_s=data.get("reply_wait", 1800),
            notify=data.get("notify", True),
            risky=data.get("risky_commands"),
            reply_entrypoints=data.get("reply_entrypoints"),
        )
    except (TypeError, ValueError):
        return Settings()


def risky_match(command: str | None, patterns: list[str]) -> str | None:
    """The first risky pattern a command matches, or None."""
    import re

    if not command:
        return None
    for p in patterns:
        try:
            if re.search(p, command, re.I):
                return p
        except re.error:
            continue
    return None
