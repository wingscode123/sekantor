"""config.toml: one read serves the hub settings and the Orca opt-in."""

from sekantor import config


def test_old_relay_settings_in_config_toml_are_ignored_not_fatal(tmp_path):
    # an owner's config.toml still has [telegram] / webhooks
    (tmp_path / "config.toml").write_text('[telegram]\nchat_id = 1\n[[webhooks]]\nurl = "https://ntfy.sh/x"\n')
    settings, problems = config.load(tmp_path)
    assert settings is not None and problems == []


def test_config_toml_feeds_settings(tmp_path):
    (tmp_path / "config.toml").write_text('quiet_hours = "22:00-07:00"\norca_pos = true\n')
    s = config.settings(tmp_path)
    assert (s.quiet_hours, s.orca_pos) == ((22 * 60, 7 * 60), True)


def test_missing_config_gives_defaults(tmp_path):
    s = config.settings(tmp_path)
    assert (s.notify, s.orca_pos) == (True, False)


def test_one_bad_value_keeps_the_others(tmp_path):
    (tmp_path / "config.toml").write_text('ignore_cwd = 5\nquiet_hours = "22:00-07:00"\norca_pos = true\n')
    settings, problems = config.load(tmp_path)
    assert settings.orca_pos is True and settings.quiet_hours == (22 * 60, 7 * 60) and len(problems) == 1


def test_keys_of_the_answering_era_are_ignored_without_a_problem(tmp_path):
    (tmp_path / "config.toml").write_text(
        'approval_wait = 30\nreply_wait = "soon"\nrisky_commands = ["x"]\nreply_entrypoints = ["cli"]\norca_pos = true\n')
    settings, problems = config.load(tmp_path)
    assert settings.orca_pos is True and problems == []


def test_doctor_names_config_problems(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from sekantor.cli import app

    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path))
    monkeypatch.setenv("SEKANTOR_URL", "http://127.0.0.1:9")
    (tmp_path / "config.toml").write_text('noitfy = true\nignore_cwd = 5\n')
    out = CliRunner().invoke(app, ["doctor"]).output
    assert "noitfy" in out and "ignore_cwd" in out


def test_doctor_names_a_broken_config_file(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from sekantor.cli import app

    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path))
    monkeypatch.setenv("SEKANTOR_URL", "http://127.0.0.1:9")
    (tmp_path / "config.toml").write_text("notify = \n")
    assert "config.toml" in CliRunner().invoke(app, ["doctor"]).output
