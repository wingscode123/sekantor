"""Children of `ronda up` end when the hub is gone (force-stopped hubs run no cleanup)."""

import os
import subprocess
import sys
import time

CHILD = "from ronda.lifeline import start_parent_watch; import time; start_parent_watch(0.2); time.sleep(30)"


def test_child_exits_when_parent_is_gone():
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    import psutil

    created = psutil.Process(parent.pid).create_time()
    env = {**os.environ, "RONDA_PARENT_PID": str(parent.pid), "RONDA_PARENT_CREATED": f"{created:.3f}"}
    child = subprocess.Popen([sys.executable, "-c", CHILD], env=env)
    time.sleep(1.5)
    assert child.poll() is None  # parent alive: child keeps running
    parent.kill()
    parent.wait(10)
    child.wait(15)
    assert child.returncode == 0


def test_without_parent_env_nothing_happens(monkeypatch):
    from ronda.lifeline import start_parent_watch

    monkeypatch.delenv("RONDA_PARENT_PID", raising=False)
    assert start_parent_watch() is False


def test_reused_pid_counts_as_gone():
    from ronda.lifeline import parent_alive

    assert parent_alive(os.getpid(), 0.0) is False
