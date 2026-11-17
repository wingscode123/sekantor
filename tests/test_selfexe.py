import sys
from pathlib import Path

from sekantor import selfexe, service


def _frozen(monkeypatch, tmp_path, name="sekantor-hub.exe", platform="win32"):
    folder = tmp_path / "First Last"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / name))
    monkeypatch.setattr(sys, "platform", platform)
    return folder


def test_self_command_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert selfexe.self_command("pos", "tmux") == [sys.executable, "-m", "sekantor.cli", "pos", "tmux"]


def test_self_command_frozen_uses_the_cli_exe_next_to_us(monkeypatch, tmp_path):
    folder = _frozen(monkeypatch, tmp_path)
    assert selfexe.self_command("pos", "openbot") == [str(folder / "sekantor.exe"), "pos", "openbot"]


def test_self_command_frozen_has_no_exe_suffix_off_windows(monkeypatch, tmp_path):
    folder = _frozen(monkeypatch, tmp_path, name="sekantor-hub", platform="linux")
    assert selfexe.self_command("up") == [str(folder / "sekantor"), "up"]


def test_hub_exe_frozen_is_the_windowed_exe(monkeypatch, tmp_path):
    folder = _frozen(monkeypatch, tmp_path, name="sekantor.exe")
    assert selfexe.hub_exe() == [str(folder / "sekantor-hub.exe")]


def test_hub_exe_from_source_keeps_pythonw(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    py = tmp_path / "python.exe"
    py.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    assert selfexe.hub_exe("win32", str(py)) == [str(tmp_path / "pythonw.exe"), "-m", "sekantor.cli"]
    assert selfexe.hub_exe("linux", "/p/python") == ["/p/python", "-m", "sekantor.cli"]


def test_frozen_service_runs_the_windowed_hub_exe(monkeypatch, tmp_path):
    folder = _frozen(monkeypatch, tmp_path)
    home = tmp_path / "Home Dir"
    p = service.plan(home, platform="win32", user="me", scratch=tmp_path)
    text = next(iter(p.files.values())).decode("utf-16")
    assert f"<Command>{folder / 'sekantor-hub.exe'}</Command>" in text
    assert "-m sekantor.cli" not in text
    assert f'<Arguments>up --no-open --log-file "{home / "hub.log"}"</Arguments>' in text


def test_hub_exe_frozen_follows_the_platform_argument(monkeypatch, tmp_path):
    folder = _frozen(monkeypatch, tmp_path, name="sekantor-hub", platform="linux")
    assert selfexe.hub_exe("win32") == [str(folder / "sekantor-hub.exe")]
