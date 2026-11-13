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

# Folders whose Claude Code runs are not agent sessions: OpenBot's own helper runs start in its
# program folder (28 of 37 "OpenBot" sessions in the first dogfooding run).
DEFAULT_IGNORE_CWD = [r"/Programs/OpenBot(/|$)", r"/OpenBot\.app/", r"^/opt/OpenBot(/|$)"]


class Settings:
    def __init__(self, approval_wait_s: int = 600, reply_wait_s: int = 1800, notify: bool = True,
                 risky: list[str] | None = None, reply_entrypoints: list[str] | None = None,
                 quiet_hours: str | None = None, ignore_cwd: list[str] | None = None, orca_pos: bool = False):
        self.approval_wait_s = max(0, min(int(approval_wait_s), 3600))
        self.reply_wait_s = max(0, min(int(reply_wait_s), 86400))
        self.notify = bool(notify)
        self.risky = list(risky) if risky is not None else list(DEFAULT_RISKY)
        self.reply_entrypoints = (list(DEFAULT_REPLY_ENTRYPOINTS) if reply_entrypoints is None
                                  else [str(e) for e in reply_entrypoints])
        self.quiet_hours = parse_quiet_hours(quiet_hours)  # FR-33: (start, end) minutes, or None
        self.ignore_cwd = list(ignore_cwd) if ignore_cwd is not None else list(DEFAULT_IGNORE_CWD)
        self.orca_pos = bool(orca_pos)  # opt-in: the orca CLI is heavy to poll

    def ignored(self, cwd: str | None) -> bool:
        import re

        if not cwd:
            return False
        path = cwd.replace("\\", "/")
        for p in self.ignore_cwd:
            try:
                if re.search(p, path, re.I):
                    return True
            except re.error:
                continue
        return False

    def quiet(self, now=None) -> bool:
        return in_quiet_hours(self.quiet_hours, now)


def parse_quiet_hours(spec: str | None) -> tuple[int, int] | None:
    """'22:00-07:00' -> (1320, 420) in minutes after midnight, local time. Bad or empty -> None."""
    import re

    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", spec or "")
    if not m:
        return None
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59 or (h1, m1) == (h2, m2):
        return None
    return h1 * 60 + m1, h2 * 60 + m2


def in_quiet_hours(window: tuple[int, int] | None, now=None) -> bool:
    if not window:
        return False
    from datetime import datetime

    t = (now or datetime.now()).astimezone()
    minute = t.hour * 60 + t.minute
    start, end = window
    return start <= minute < end if start < end else (minute >= start or minute < end)


def config_path(base: Path | None = None) -> Path:
    return (base or home()) / "config.toml"


def read_toml(base: Path | None = None) -> dict:
    """config.toml as a dict; a missing or broken file reads as empty."""
    import tomllib

    try:
        with open(config_path(base), "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


# config.toml key -> Settings argument
SETTING_KEYS = {"approval_wait": "approval_wait_s", "reply_wait": "reply_wait_s", "notify": "notify",
                "risky_commands": "risky", "reply_entrypoints": "reply_entrypoints", "quiet_hours": "quiet_hours",
                "ignore_cwd": "ignore_cwd", "orca_pos": "orca_pos"}


def settings(base: Path | None = None) -> Settings:
    """Read config.toml; a missing or broken file gives the defaults."""
    data = read_toml(base)
    try:
        return Settings(**{arg: data[key] for key, arg in SETTING_KEYS.items() if key in data})
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
