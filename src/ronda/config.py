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
