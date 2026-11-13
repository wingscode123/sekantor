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
        self.events, self.actions = [], {}

    def post_event(self, ev):
        self.events.append(ev)
        return True

    def next_action(self, sid, kind, rid):
        return self.actions.pop((sid, rid), None)


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


def test_approval_round_trip(tmp_path):
    pos, ob, hub, _ = setup(tmp_path)
    pos.tick()
    ob.pending["approvals"] = [APPROVAL]
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_approval" and ev["capabilities"] == ["approve", "deny"]
    assert ev["request"] == {"kind": "tool", "tool": "command", "input": "npm publish", "id": "r1"}
    assert ev["workspace"]["cwd"] == "C:/work/lib"
    hub.actions[("openbot:agent-1", "r1")] = {"type": "deny"}
    pos.tick()
    assert ob.posts == [("/v1/agents/agent-1/approvals/r1/respond", {"decision": "decline"})]
    ob.pending["approvals"] = []
    pos.tick()
    assert hub.events[-1]["status"] == "done"


def test_single_question_answered_by_reply(tmp_path):
    pos, ob, hub, _ = setup(tmp_path)
    ob.pending["prompts"] = [{"requestId": "p9", "requiresOpenBot": False, "questions": [
        {"id": "q1", "header": "Branch", "question": "Which branch?", "options": [{"label": "main", "description": ""},
                                                                              {"label": "dev", "description": ""}]}]}]
    pos.tick()
    ev = hub.events[-1]
    assert ev["status"] == "waiting_input" and ev["capabilities"] == ["reply"] and ev["summary"] == "Which branch? (main, dev)"
    hub.actions[("openbot:agent-1", "p9")] = {"type": "reply", "text": "dev"}
    pos.tick()
    assert ob.posts == [("/v1/agents/agent-1/prompts/p9/answer", {"answers": {"q1": ["dev"]}})]


def test_things_only_openbot_can_answer_get_no_buttons():
    d = describe({"prompts": [{"requestId": "s", "requiresOpenBot": True, "questions": []}]})
    assert d["status"] == "waiting_input" and d["capabilities"] == [] and "in OpenBot" in d["summary"]
    d = describe({"browserTakeovers": [{"requestId": "b", "requiresOpenBot": True}]})
    assert d["capabilities"] == [] and "browser" in d["summary"]
    two = {"requestId": "m", "requiresOpenBot": False, "questions": [{"id": "a"}, {"id": "b"}]}
    assert describe({"prompts": [two]})["capabilities"] == []


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
