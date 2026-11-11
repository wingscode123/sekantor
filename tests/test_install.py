import json
from pathlib import Path

import pytest

from ronda.pos.claude_code import install as inst

EXE = Path("/opt/ronda/bin/ronda-hook")
ORCA = {"type": "command", "command": "C:/Users/u/.orca/agent-hooks/orca-agent-hook.exe claude", "timeout": 10}


def settings(tmp_path, data):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(data))
    return p


def test_install_keeps_other_hooks_and_settings(tmp_path):
    p = settings(tmp_path, {"theme": "dark", "hooks": {"Stop": [{"hooks": [ORCA]}], "TeammateIdle": [{"hooks": [ORCA]}]}})
    r = inst.install(p, EXE)
    data = json.loads(p.read_text())
    assert data["theme"] == "dark"
    assert data["hooks"]["Stop"][0]["hooks"] == [ORCA]
    assert data["hooks"]["TeammateIdle"] == [{"hooks": [ORCA]}]
    assert set(inst.EVENTS) <= set(data["hooks"])
    assert r.backup and json.loads(r.backup.read_text())["theme"] == "dark"
    ours = data["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    assert ours == {"type": "command", "command": EXE.as_posix(), "args": [], "async": True, "timeout": 10}
    end = data["hooks"]["SessionEnd"][0]["hooks"][0]
    assert "async" not in end and end["timeout"] == 2
    perm = data["hooks"]["PermissionRequest"][0]["hooks"][0]
    assert "async" not in perm and perm["timeout"] == 600 + inst.MARGIN_S
    stop = data["hooks"]["Stop"][1]["hooks"][0]
    assert stop["async"] is True and stop["asyncRewake"] is True and stop["timeout"] == 1800 + inst.MARGIN_S
    assert inst.inspect(p).current_shape


def test_install_is_idempotent(tmp_path):
    p = settings(tmp_path, {})
    inst.install(p, EXE)
    inst.install(p, EXE)
    data = json.loads(p.read_text())
    assert all(len(data["hooks"][e]) == 1 for e in inst.EVENTS)


def test_uninstall_removes_only_ours(tmp_path):
    original = {"hooks": {"Stop": [{"hooks": [ORCA]}]}, "model": "opus"}
    p = settings(tmp_path, original)
    inst.install(p, EXE)
    r = inst.uninstall(p)
    assert r.changed == len(inst.EVENTS)
    assert json.loads(p.read_text()) == original


def test_uninstall_drops_empty_hooks_key(tmp_path):
    p = settings(tmp_path, {"model": "opus"})
    inst.install(p, EXE)
    inst.uninstall(p)
    assert json.loads(p.read_text()) == {"model": "opus"}
    assert inst.uninstall(p).changed == 0


def test_invalid_json_is_never_overwritten(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ not json")
    with pytest.raises(ValueError):
        inst.install(p, EXE)
    assert p.read_text() == "{ not json"


def test_missing_file_is_created(tmp_path):
    p = tmp_path / ".claude" / "settings.local.json"
    r = inst.install(p, EXE)
    assert r.backup is None and p.exists()
    info = inst.inspect(p)
    assert info.complete and info.commands == {EXE.as_posix()}


def test_windows_exe_name_is_ours():
    assert inst.is_ours({"command": r"C:\venv\Scripts\ronda-hook.exe"})
    assert not inst.is_ours(ORCA)


def test_old_m1_install_is_flagged(tmp_path):
    p = settings(tmp_path, {"hooks": {
        "PermissionRequest": [{"hooks": [{"type": "command", "command": EXE.as_posix(), "args": [], "async": True}]}],
        "Stop": [{"hooks": [{"type": "command", "command": EXE.as_posix(), "args": [], "async": True}]}],
    }})
    assert not inst.inspect(p).current_shape
