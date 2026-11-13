"""Kentongan: native desktop notifications from the hub (ADR-0009).

No extra dependencies: a WinRT toast through PowerShell on Windows, osascript on macOS, notify-send on
Linux. Text goes to the child process as arguments or environment variables, never pasted into a
script, and never includes tool input (it can hold secrets).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ronda import labels
from ronda.hub.status import SessionState
from ronda.schema import Status

MIN_GAP_S = 10.0

# PowerShell's own AppUserModelID: a toast needs a registered app id to show on Windows 10/11.
_PS_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_PS_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $xml.GetElementsByTagName('text')
$null = $t.Item(0).AppendChild($xml.CreateTextNode($env:RONDA_TITLE))
$null = $t.Item(1).AppendChild($xml.CreateTextNode($env:RONDA_BODY))
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:RONDA_APP_ID).Show($toast)
"""


def should_notify(prev: Status | None, new: Status) -> bool:
    if prev is new:
        return False
    if new in (Status.waiting_approval, Status.error):
        return True
    # a finished turn, or an idle agent asking something (OpenBot); not a fresh session
    return new is Status.waiting_input and prev in (Status.running, Status.done)


def message(s: SessionState) -> tuple[str, str]:
    who = labels.source(s.source)
    if s.host:
        who += f" in {labels.host(s.host.app)}"
    project = Path(s.workspace.cwd).name if s.workspace.cwd else None
    return labels.TITLES[s.status.value], f"{who}, {project}" if project else who


def send_native(title: str, body: str) -> None:
    """Fire and forget. Raises nothing."""
    try:
        if sys.platform == "win32":
            env = {**os.environ, "RONDA_TITLE": title, "RONDA_BODY": body, "RONDA_APP_ID": _PS_APP_ID}
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _PS_TOAST],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["osascript", "-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
                 "-e", "end run", title, body],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "--app-name=Ronda", title, body],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class Notifier:
    def __init__(self, enabled: bool = True, sender: Callable[[str, str], None] | None = None,
                 min_gap_s: float = MIN_GAP_S, quiet: Callable[[], bool] = lambda: False):
        self.enabled = enabled
        self.quiet = quiet
        self.sender = sender
        self.min_gap_s = min_gap_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def maybe(self, prev: SessionState | None, new: SessionState) -> bool:
        if not self.enabled or not should_notify(prev.status if prev else None, new.status):
            return False
        if new.snoozed(datetime.now(timezone.utc)) or self.quiet():  # FR-15, FR-33
            return False
        now = time.monotonic()
        with self._lock:
            if now - self._last.get(new.session_id, -1e9) < self.min_gap_s:
                return False
            self._last[new.session_id] = now
        title, body = message(new)
        sender = self.sender or send_native
        threading.Thread(target=sender, args=(title, body), daemon=True).start()
        return True
