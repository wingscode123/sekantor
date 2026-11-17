"""Child processes of `sekantor up` (pos) end when the hub process is gone.

A force-stopped hub (Task Scheduler's End, a crash, TerminateProcess) runs no cleanup, so its
children would keep running. `sekantor up` passes its PID and start time; each child checks them.
"""

from __future__ import annotations

import os
import threading
import time


def parent_env() -> dict[str, str]:
    import psutil

    me = psutil.Process()
    return {"SEKANTOR_PARENT_PID": str(me.pid), "SEKANTOR_PARENT_CREATED": f"{me.create_time():.3f}"}


def parent_alive(pid: int, created: float) -> bool:
    import psutil

    try:
        return abs(psutil.Process(pid).create_time() - created) < 1.0  # same process, not a reused PID
    except psutil.Error:
        return False


def start_parent_watch(interval: float = 5.0) -> bool:
    """Exit this process when the parent hub is gone. No-op when not started by `sekantor up`."""
    try:
        pid = int(os.environ["SEKANTOR_PARENT_PID"])
        created = float(os.environ["SEKANTOR_PARENT_CREATED"])
    except (KeyError, ValueError):
        return False

    def watch() -> None:
        while True:
            time.sleep(interval)
            if not parent_alive(pid, created):
                os._exit(0)

    threading.Thread(target=watch, daemon=True, name="sekantor-parent-watch").start()
    return True
