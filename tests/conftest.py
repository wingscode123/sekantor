import os
import subprocess

import pytest

_SERVICE_TOOLS = {"schtasks", "launchctl", "systemctl"}


def _tool(args) -> str:
    argv = args if isinstance(args, (list, tuple)) else [args]
    first = os.fspath(argv[0]) if argv else ""
    return os.path.splitext(os.path.basename(first))[0].lower()


class _GuardedPopen(subprocess.Popen):
    def __init__(self, args, *a, **kw):
        if _tool(args) in _SERVICE_TOOLS:
            raise AssertionError(f"test tried to run the real service tool {_tool(args)!r}: {args!r}")
        super().__init__(args, *a, **kw)


@pytest.fixture(autouse=True)
def _isolate(tmp_path_factory, monkeypatch):
    """Never touch the real home, the real service manager or real desktop notifications."""
    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path_factory.mktemp("sekantor-home")))
    fake_home = str(tmp_path_factory.mktemp("user-home"))
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setenv("USERPROFILE", fake_home)

    def _blocked(*a, **kw):
        raise AssertionError("test touched the real service manager; monkeypatch sekantor.service explicitly")

    monkeypatch.setattr("sekantor.service.run", _blocked)
    monkeypatch.setattr("sekantor.service.installed", lambda plan: False)
    monkeypatch.setattr(subprocess, "Popen", _GuardedPopen)

    sent = []
    monkeypatch.setattr("sekantor.hub.notify.send_native", lambda title, body: sent.append((title, body)))
    return sent


def test_guard_blocks_real_service_tools():
    from sekantor import service

    with pytest.raises(AssertionError):
        service.run([["schtasks", "/Query"]])
    with pytest.raises(AssertionError, match="schtasks"):
        subprocess.run(["schtasks", "/Query"])
