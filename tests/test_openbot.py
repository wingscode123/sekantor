"""OpenBot pos against a fake OpenBot Local scripts API (shapes from nightly-labs/openbot docs/automation.md)."""

import json

import httpx

from ronda.pos.openbot.pos import OpenBotApi, OpenBotPos, describe

AGENT = {"id": "agent-1", "name": "Ada", "routines": []}


class FakeOpenBot:
    def __init__(self, token="t1"):
        self.token = token
        self.pending = {"prompts": [], "approvals": [], "browserTakeovers": []}
        self.agents = [AGENT]
        self.posts = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        assert "origin" not in request.headers  # OpenBot refuses requests with an Origin header
        path = request.url.path
        if request.method == "GET" and path == "/v1/agents":
            return httpx.Response(200, json=self.agents)
        if request.method == "GET" and path.endswith("/pending"):
            return httpx.Response(200, json=self.pending)
        if request.method == "POST":
            self.posts.append((path, json.loads(request.content)))
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": "not found"})


class FakeHub:
    def __init__(self):
        self.events = []

    def post_event(self, ev):
        self.events.append(ev)
        return True


def setup(tmp_path, ob=None):
    ob = ob or FakeOpenBot()
    folder = tmp_path / "automation"
    folder.mkdir()
    (folder / "url").write_text("http://127.0.0.1:43123\n")
    (folder / "token").write_text(ob.token + "\n")
    api = OpenBotApi(folder, transport=httpx.MockTransport(ob.handler))
    hub = FakeHub()
    return OpenBotPos(api, hub, agents_root=tmp_path / "Agents"), ob, hub, folder


APPROVAL = {"requestId": "r1", "agentId": "agent-1", "threadId": "t", "turnId": "u", "kind": "command",
            "command": "npm publish", "cwd": "C:/work/lib", "reason": "publish the package", "grantRoot": None,
            "permissions": None}


def test_idle_agent_is_a_done_session(tmp_path):
    pos, ob, hub, _ = setup(tmp_path)
    pos.tick()
    [ev] = hub.events
    assert ev["type"] == "session_started" and ev["session_id"] == "openbot:agent-1" and ev["status"] == "done"
    assert ev["host"]["app"] == "openbot" and ev["agent"]["name"] == "Ada"
    pos.tick()
    assert len(hub.events) == 1  # nothing changed


def test_an_approval_is_reported_and_never_answered(tmp_path):
    pos, ob, hub, _ = setup(tmp_path)
    pos.tick()
    ob.pending["approvals"] = [APPROVAL]
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_approval" and "capabilities" not in ev
    assert ev["request"] == {"kind": "tool", "tool": "command", "input": "npm publish", "id": "r1"}
    assert ev["workspace"]["cwd"] == "C:/work/lib"
    pos.tick()
    assert ob.posts == []  # ADR-0021: it only reads
    ob.pending["approvals"] = []
    pos.tick()
    assert hub.events[-1]["status"] == "done"


def test_a_single_question_is_reported(tmp_path):
    pos, ob, hub, _ = setup(tmp_path)
    ob.pending["prompts"] = [{"requestId": "p9", "requiresOpenBot": False, "questions": [
        {"id": "q1", "header": "Branch", "question": "Which branch?", "options": [{"label": "main", "description": ""},
                                                                              {"label": "dev", "description": ""}]}]}]
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_input" and ev["summary"] == "Which branch? (main, dev)"
    pos.tick()
    assert ob.posts == []


def test_things_only_openbot_can_answer_say_so():
    d = describe({"prompts": [{"requestId": "s", "requiresOpenBot": True, "questions": []}]})
    assert d["status"] == "waiting_input" and d["request"]["kind"] == "question" and "in OpenBot" in d["summary"]
    d = describe({"browserTakeovers": [{"requestId": "b", "requiresOpenBot": True}]})
    assert d["request"]["kind"] == "question" and "browser" in d["summary"]


def test_new_token_after_openbot_restart(tmp_path):
    pos, ob, hub, folder = setup(tmp_path)
    pos.tick()
    ob.token = "t2"
    (folder / "token").write_text("t2")
    ob.pending["approvals"] = [APPROVAL]
    pos.tick()
    assert hub.events[-1]["status"] == "waiting_approval"


def test_sessions_end_when_openbot_quits(tmp_path):
    pos, ob, hub, folder = setup(tmp_path)
    pos.tick()
    (folder / "url").unlink()
    (folder / "token").unlink()
    pos.api.close()
    pos.tick()
    assert hub.events[-1]["type"] == "session_ended" and hub.events[-1]["session_id"] == "openbot:agent-1"


def test_not_running_is_quiet(tmp_path):
    api = OpenBotApi(tmp_path / "nowhere")
    hub = FakeHub()
    OpenBotPos(api, hub).tick()
    assert hub.events == []


def test_an_unreachable_openbot_is_logged_once_and_its_return_too(tmp_path, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO, "ronda.pos.openbot")
    pos, ob, hub, _ = setup(tmp_path)
    real_get = pos.api.get

    def refused(path):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(pos.api, "get", refused)
    for _ in range(3):
        pos.tick()
    monkeypatch.setattr(pos.api, "get", real_get)
    pos.tick()
    pos.tick()
    lines = [r.getMessage() for r in caplog.records if r.name == "ronda.pos.openbot"]
    assert sum("not reachable" in m for m in lines) == 1
    assert sum("reachable again" in m for m in lines) == 1
