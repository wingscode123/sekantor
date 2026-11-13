"""config.toml: one read serves the hub settings, the Orca opt-in and the webhooks."""

from ronda import config
from ronda.relay.runner import load_webhooks


def test_config_toml_feeds_settings_and_webhooks(tmp_path):
    (tmp_path / "config.toml").write_text(
        'approval_wait = 30\norca_pos = true\n[[webhooks]]\nurl = "https://ntfy.sh/x"\nformat = "ntfy"\n')
    s = config.settings(tmp_path)
    assert (s.approval_wait_s, s.reply_wait_s, s.orca_pos) == (30, 1800, True)
    hooks, errors = load_webhooks(tmp_path)
    assert [h.url for h in hooks] == ["https://ntfy.sh/x"] and errors == []


def test_missing_config_gives_defaults(tmp_path):
    s = config.settings(tmp_path)
    assert (s.approval_wait_s, s.notify, s.orca_pos) == (600, True, False)
    assert load_webhooks(tmp_path) == ([], [])


def test_one_bad_value_keeps_the_others(tmp_path):
    (tmp_path / "config.toml").write_text('approval_wait = "10m"\nreply_wait = 60\norca_pos = true\n')
    s = config.settings(tmp_path)
    assert (s.approval_wait_s, s.reply_wait_s, s.orca_pos) == (600, 60, True)


def test_doctor_names_config_problems(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from ronda.cli import app

    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    monkeypatch.setenv("RONDA_URL", "http://127.0.0.1:9")
    (tmp_path / "config.toml").write_text('aproval_wait = 30\nreply_wait = "soon"\n')
    out = CliRunner().invoke(app, ["doctor"]).output
    assert "aproval_wait" in out and "reply_wait" in out


def test_doctor_names_a_broken_config_file(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from ronda.cli import app

    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    monkeypatch.setenv("RONDA_URL", "http://127.0.0.1:9")
    (tmp_path / "config.toml").write_text("notify = \n")
    assert "config.toml" in CliRunner().invoke(app, ["doctor"]).output
