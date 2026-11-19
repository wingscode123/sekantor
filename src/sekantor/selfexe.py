"""How to launch ourselves: from source (`python -m sekantor.cli`) or frozen (PyInstaller exes in one folder)."""

from __future__ import annotations

import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _sibling(stem: str, platform: str) -> str:
    name = stem + (".exe" if platform == "win32" else "")
    return str(Path(sys.executable).with_name(name))


def self_command(*args: str) -> list[str]:
    """Command that runs the `sekantor` CLI with ``args`` in a child process."""
    if frozen():
        return [_sibling("sekantor", sys.platform), *args]
    return [sys.executable, "-m", "sekantor.cli", *args]


def hub_exe(platform: str = sys.platform, python: str = sys.executable) -> list[str]:
    """Prefix of the command that runs the hub without a console window."""
    if frozen():
        return [_sibling("sekantor-hub", platform)]
    if platform == "win32":
        exe = Path(python)
        w = exe.with_name("pythonw.exe")
        exe = w if w.exists() or not exe.exists() else exe
        return [str(exe), "-m", "sekantor.cli"]
    return [python, "-m", "sekantor.cli"]
