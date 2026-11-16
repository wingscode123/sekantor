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


def _old_home(tmp_path):
    import sqlite3

    old = tmp_path / ".ronda"
    old.mkdir()
    (old / "token").write_text("t")
    (old / "config.toml").write_text("notify = false\n")
    (old / "hosts.cache.json").write_text("{}")
    db = sqlite3.connect(old / "ronda.db")
    db.execute("CREATE TABLE events (id INTEGER)")
    db.execute("INSERT INTO events VALUES (1)")
    db.commit()
    db.close()
    return old


def test_migrate_copies_token_config_and_db(tmp_path):
    import sqlite3

    old, new = _old_home(tmp_path), tmp_path / ".sekantor"
    assert config.migrate_home(old, new) is True
    assert (new / "token").read_text() == "t" and (new / "config.toml").read_text() == "notify = false\n"
    assert (new / "hosts.cache.json").exists()
    assert sqlite3.connect(new / "sekantor.db").execute("SELECT count(*) FROM events").fetchone() == (1,)
    assert (old / "ronda.db").exists() and (old / "token").exists()  # old left alone
    import os, sys
    if sys.platform != "win32":
        assert os.stat(new / "token").st_mode & 0o777 == 0o600


def test_migrate_never_overwrites(tmp_path):
    old, new = _old_home(tmp_path), tmp_path / ".sekantor"
    new.mkdir()
    (new / "token").write_text("mine")
    assert config.migrate_home(old, new) is False
    assert (new / "token").read_text() == "mine" and not (new / "sekantor.db").exists()


def test_migrate_without_an_old_home_does_nothing(tmp_path):
    assert config.migrate_home(tmp_path / ".ronda", tmp_path / ".sekantor") is False
    assert not (tmp_path / ".sekantor").exists()


def test_sekantor_home_env_sets_the_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path / "x"))
    assert config.home() == tmp_path / "x"


def test_legacy_migration_runs_from_the_user_home_unless_sekantor_home_is_set(tmp_path, monkeypatch):
    _old_home(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("SEKANTOR_HOME", raising=False)
    assert config.migrate_legacy_home() is True and (tmp_path / ".sekantor" / "token").read_text() == "t"
    monkeypatch.setenv("SEKANTOR_HOME", str(tmp_path / "elsewhere"))
    assert config.migrate_legacy_home() is False and not (tmp_path / "elsewhere").exists()
