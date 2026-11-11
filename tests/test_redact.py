import pytest

from ronda.relay.redact import redact


@pytest.mark.parametrize("text, leaked", [
    ("export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx", "abcdefghijklmnop"),
    ("GITHUB_TOKEN=ghp_0123456789abcdefghijABCDEFGHIJ012345 gh pr list", "ghp_0123456789"),
    ("curl -H 'Authorization: Bearer eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl' https://api.x", "eyJhbGciOi"),
    ("psql postgres://admin:hunter2@db.internal:5432/app", "hunter2"),
    ("mysql -u root --password=hunter2 app", "hunter2"),
    ("aws s3 ls # key AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
    ("SLACK=xoxb-123456789012-abcdefABCDEF", "xoxb-123456789012"),
    ("echo $DB_PASSWORD; DB_PASSWORD: s3cr3t!", "s3cr3t!"),
    ("claude --api-key sk-ant-api03-abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnop"),
    ("key AIzaSyA-1234567890abcdefghijklmnopqrstu", "AIzaSyA-1234567890"),
    ("ssh-keygen; secret_key = 'x9Y8z7W6v5'", "x9Y8z7W6v5"),
])
def test_secrets_are_masked(text, leaked):
    out = redact(text)
    assert leaked not in out and "<redacted>" in out


@pytest.mark.parametrize("text", [
    "npm test", "git push origin main", "docker compose up -d", "cat README.md",
    "echo $DB_PASSWORD", "pytest -k token_mode", "git log --oneline -5",
])
def test_ordinary_commands_untouched(text):
    assert redact(text) == text


def test_none_and_long():
    assert redact(None) is None
    assert redact("a" * 5000, limit=100).endswith("…") and len(redact("a" * 5000, limit=100)) == 100
