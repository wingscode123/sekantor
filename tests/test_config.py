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
