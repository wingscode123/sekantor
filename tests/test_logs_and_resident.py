"""Process set-up: quiet library logs, and on Windows a hub that stays in RAM (ADR-0020)."""

import logging
import subprocess
import sys

import pytest

from ronda import logs, resident


def test_http_libraries_log_only_problems():
    # httpx logs every request at INFO: the OpenBot pos wrote 16,845 lines to hub.log in 1.5 h.
    saved = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    try:
        logs.setup("relay")
        assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("httpcore").getEffectiveLevel() == logging.WARNING
    finally:
        for n, level in saved.items():
            logging.getLogger(n).setLevel(level)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows working sets")
def test_the_hub_keeps_a_hard_minimum_working_set():
    # In a child process, so the test run itself is not pinned.
    code = (
        "import ctypes, ctypes.wintypes as w; from ronda import resident\n"
        "assert resident.keep_resident(64 * 2**20) is None\n"
        "k = ctypes.WinDLL('kernel32'); k.GetCurrentProcess.restype = w.HANDLE\n"
        "k.GetProcessWorkingSetSizeEx.argtypes = [w.HANDLE] + [ctypes.c_void_p] * 3\n"
        "lo, hi, flags = ctypes.c_size_t(), ctypes.c_size_t(), w.DWORD()\n"
        "assert k.GetProcessWorkingSetSizeEx(k.GetCurrentProcess(), ctypes.byref(lo), ctypes.byref(hi), ctypes.byref(flags))\n"
        "print(lo.value, flags.value)\n"
    )
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    lo, flags = map(int, p.stdout.split())
    assert lo >= 64 * 2**20 and flags & 1  # QUOTA_LIMITS_HARDWS_MIN_ENABLE


def test_elsewhere_it_says_why_it_did_nothing(monkeypatch):
    monkeypatch.setattr(resident.sys, "platform", "linux")
    assert resident.keep_resident() == "only on Windows"
