"""A minimal Ronda pos, standard library only, about 70 lines. Copy it to start your own.

It reports a pretend agent that works, then asks for approval, and acts on Approve/Deny from Ronda.
Run `ronda up`, then `python examples/pos_minimal.py`, and answer the card in the inbox.

A real pos replaces `watch_agent()` with how your platform shows its agent's state, and `answer()`
with how it hands the answer back (an API call, keys typed into a terminal, ...).
"""

import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

HUB = os.environ.get("RONDA_URL", "http://127.0.0.1:7878")
TOKEN = (Path(os.environ.get("RONDA_HOME", Path.home() / ".ronda")) / "token").read_text().strip()
SESSION = f"example:{uuid.uuid4().hex[:8]}"  # stable for one run of one agent; prefix = your pos


def call(method, path, body=None):
    req = urllib.request.Request(HUB + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"null")


def event(status, summary, type="status_changed", request=None, capabilities=()):
    """Schema v1: see src/ronda/schema.py. Unknown fields are ignored, so it is safe to add your own."""
    call("POST", "/v1/events", {
        "v": 1, "event_id": uuid.uuid4().hex, "ts": datetime.now(timezone.utc).isoformat(),
        "source": "example", "session_id": SESSION, "agent": {"name": "example-agent"},
        "workspace": {"cwd": os.getcwd()}, "host": {"app": "terminal", "confidence": 1.0, "via": ["example"]},
        "type": type, "status": status, "summary": summary, "request": request, "capabilities": list(capabilities),
    })


def next_action(request_id, kind="approval"):
    """Ask the hub for the answer to one request; wait up to 25 s per call."""
    q = urllib.parse.urlencode({"for": kind, "request_id": request_id, "wait": 25})
    return call("GET", f"/v1/sessions/{urllib.parse.quote(SESSION, safe='')}/actions/next?{q}")


def watch_agent():
    """Pretend agent: works for a few seconds, then asks to run a command."""
    event("running", "Reading the code", type="session_started")
    time.sleep(3)
    return "npm run deploy"


def answer(approved):
    print("approved, running it" if approved else "denied, skipping it")


def main():
    command = watch_agent()
    rid = uuid.uuid4().hex  # one id per question: an answer always names the question it answers
    event("waiting_approval", f"Wants to run: {command}", capabilities=["approve", "deny"],
          request={"kind": "tool", "tool": "shell", "input": command, "id": rid})
    print(f"Waiting for Approve/Deny on {SESSION} in the inbox ...")
    while True:
        result = next_action(rid)
        if result["action"]:
            answer(result["action"]["type"] == "approve")
            break
        if result["reason"] != "timeout":
            print("answered elsewhere")
            break
    event("running", "Back to work")
    event("ended", "Done", type="session_ended")


if __name__ == "__main__":
    main()
