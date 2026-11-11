import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path_factory, monkeypatch):
    """Never touch the real ~/.ronda, and never pop real desktop notifications."""
    monkeypatch.setenv("RONDA_HOME", str(tmp_path_factory.mktemp("ronda-home")))
    sent = []
    monkeypatch.setattr("ronda.hub.notify.send_native", lambda title, body: sent.append((title, body)))
    return sent
