"""config.toml: one read serves the hub settings, the Orca opt-in and the webhooks."""

from ronda import config
from ronda.relay.runner import load_webhooks


def test_config_toml_feeds_settings_and_webhooks(tmp_path):
    (tmp_path / "config.toml").write_text(
        'quiet_hours = "22:00-07:00"\norca_pos = true\n[[webhooks]]\nurl = "https://ntfy.sh/x"\nformat = "ntfy"\n')
    s = config.settings(tmp_path)
    assert (s.quiet_hours, s.orca_pos) == ((22 * 60, 7 * 60), True)
    hooks, errors = load_webhooks(tmp_path)
    assert [h.url for h in hooks] == ["https://ntfy.sh/x"] and errors == []


def test_missing_config_gives_defaults(tmp_path):
    s = config.settings(tmp_path)
    assert (s.notify, s.orca_pos) == (True, False)
    assert load_webhooks(tmp_path) == ([], [])


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

    from ronda.cli import app

    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    monkeypatch.setenv("RONDA_URL", "http://127.0.0.1:9")
    (tmp_path / "config.toml").write_text('noitfy = true\nignore_cwd = 5\n')
    out = CliRunner().invoke(app, ["doctor"]).output
    assert "noitfy" in out and "ignore_cwd" in out


def test_doctor_names_a_broken_config_file(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from ronda.cli import app

    monkeypatch.setenv("RONDA_HOME", str(tmp_path))
    monkeypatch.setenv("RONDA_URL", "http://127.0.0.1:9")
    (tmp_path / "config.toml").write_text("notify = \n")
    assert "config.toml" in CliRunner().invoke(app, ["doctor"]).output
