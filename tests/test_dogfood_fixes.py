"""Fixes from the first dogfooding run (2026-11-11)."""

import json
from datetime import datetime, timedelta, timezone

from ronda.config import Settings
from ronda.hub.status import apply
from ronda.pos.claude_code import install as inst
from ronda.pos.claude_code.translate import translate
from ronda.schema import Event, Status

T0 = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)

ASK = {"hook_event_name": "PermissionRequest", "session_id": "s1", "tool_name": "AskUserQuestion",
       "tool_input": {"questions": [{"question": "Which channel for the phone?", "header": "Channel",
                                     "options": [{"label": "ntfy"}, {"label": "Telegram"}], "multiSelect": False}]}}


# --- 4: AskUserQuestion is a question, not an approval -----------------------------

def test_ask_user_question_is_a_question():
    ev = translate(ASK)
    assert ev["status"] == "waiting_input"
    assert ev["request"] == {"kind": "question", "tool": "AskUserQuestion", "id": ev["event_id"]}
    assert ev["summary"] == "Asks: Which channel for the phone? (ntfy, Telegram)"
    assert "capabilities" not in ev


def test_permission_notification_does_not_turn_a_question_into_an_approval():
    def ev(i, status, **kw):
        return Event(event_id=f"e{i}", ts=T0 + timedelta(seconds=i), source="claude-code", session_id="claude:s1",
                     status=status, **kw)

    s = apply(None, ev(0, Status.running))
    s = apply(s, ev(1, Status.waiting_input, request={"kind": "question", "tool": "AskUserQuestion", "id": "q1"},
                    summary="Asks: Which channel?"))
    s = apply(s, ev(7, Status.waiting_approval))  # Notification permission_prompt ~6 s later
    assert s.status is Status.waiting_input and s.request.id == "q1"
    s = apply(s, ev(9, Status.running))  # answered
    assert s.status is Status.running


# --- 1: SessionEnd gets enough time ---------------------------------------------------

def test_session_end_hook_has_a_longer_budget(tmp_path):
    p = tmp_path / "settings.json"
    inst.install(p, inst.Path("/x/ronda-hook"))
    end = json.loads(p.read_text())["hooks"]["SessionEnd"][0]["hooks"][0]
    assert end["timeout"] >= 5 and "async" not in end


# --- 2: OpenBot's own helper runs are not sessions --------------------------------------

class FakeWatchdog:
    """A real Watchdog calls os._exit at its deadline, which would end the test run."""

    def remaining(self):
        return 60.0


def test_openbot_internal_runs_are_ignored(monkeypatch, tmp_path):
    from ronda.pos.claude_code import hook

    sent = []
    monkeypatch.setattr(hook, "post", lambda event, timeout: sent.append(event))
    payload = {"hook_event_name": "SessionStart", "session_id": "x", "source": "startup",
               "cwd": r"C:\Users\me\AppData\Local\Programs\OpenBot"}
    code = hook.run(json.dumps(payload).encode(), {}, FakeWatchdog())
    assert code == 0 and sent == []
    payload["cwd"] = r"C:\Users\me\OpenBot\Agents\agent-1"  # a real agent folder is still reported
    hook.run(json.dumps(payload).encode(), {}, FakeWatchdog())
    assert len(sent) >= 1


def test_ignore_list_comes_from_config(tmp_path):
    (tmp_path / "config.toml").write_text('ignore_cwd = ["/scratch/"]\n')
    from ronda.config import settings

    s = settings(tmp_path)
    assert s.ignored("D:/work/scratch/demo") and not s.ignored("D:/work/app")
    assert Settings().ignored("/Applications/OpenBot.app/Contents/Resources")
