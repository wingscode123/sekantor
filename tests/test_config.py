"""config.toml: one read serves the hub settings and the Orca opt-in."""

from ronda import config


def test_old_relay_settings_in_config_toml_are_ignored_not_fatal(tmp_path):
    # an owner's config.toml still has [telegram] / webhooks
    (tmp_path / "config.toml").write_text('[telegram]\nchat_id = 1\n[[webhooks]]\nurl = "https://ntfy.sh/x"\n')
    settings, problems = config.load(tmp_path)
    assert settings is not None and problems == []


def test_config_toml_feeds_settings(tmp_path):
    (tmp_path / "config.toml").write_text("approval_wait = 30\norca_pos = true\n")
    s = config.settings(tmp_path)
    assert (s.approval_wait_s, s.reply_wait_s, s.orca_pos) == (30, 1800, True)


def test_missing_config_gives_defaults(tmp_path):
    s = config.settings(tmp_path)
    assert (s.approval_wait_s, s.notify, s.orca_pos) == (600, True, False)


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
