import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path_factory, monkeypatch):
    """Never touch the real ~/.sekantor, and never pop real desktop notifications."""
    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path_factory.mktemp("sekantor-home")))
    sent = []
    monkeypatch.setattr("sekantor.hub.notify.send_native", lambda title, body: sent.append((title, body)))
    return sent
