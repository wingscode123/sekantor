"""Logging for Ronda's processes (hub, relay, pos): one line per message, tagged with the process."""

from __future__ import annotations

import logging


def setup(name: str) -> None:
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {name} %(message)s", datefmt="%H:%M:%S")
    # httpx logs every request at INFO; a pos polling every 2 s fills the service log with them.
    for lib in ("httpx", "httpcore"):
        logging.getLogger(lib).setLevel(logging.WARNING)
