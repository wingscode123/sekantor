"""A minimal SeKantor pos, standard library only, about 50 lines. Copy it to start your own.

It reports a pretend agent that works, then waits for approval, then goes on. SeKantor only watches
(ADR-0021): you answer in the agent's own app, and the pos just reports what happens.
Run `sekantor up`, then `python examples/pos_minimal.py`, and watch the card in the inbox.

A real pos replaces `watch_agent()` with how your platform shows its agent's state.
"""

import json
import os
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

HUB = os.environ.get("SEKANTOR_URL", "http://127.0.0.1:7878")
TOKEN = (Path(os.environ.get("SEKANTOR_HOME", Path.home() / ".sekantor")) / "token").read_text().strip()
SESSION = f"example:{uuid.uuid4().hex[:8]}"  # stable for one run of one agent; prefix = your pos
WAIT_S = float(os.environ.get("EXAMPLE_WAIT_S", "5"))  # how long the pretend agent waits for you


def call(method, path, body=None, timeout=10):
    req = urllib.request.Request(HUB + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def event(status, summary, type="status_changed", request=None):
    """Schema v1: see src/sekantor/schema.py. Unknown fields are ignored, so it is safe to add your own."""
    call("POST", "/v1/events", {
        "v": 1, "event_id": uuid.uuid4().hex, "ts": datetime.now(timezone.utc).isoformat(),
        "source": "example", "session_id": SESSION, "agent": {"name": "example-agent"},
        "workspace": {"cwd": os.getcwd()}, "host": {"app": "terminal", "confidence": 1.0, "via": ["example"]},
        "type": type, "status": status, "summary": summary, "request": request,
    })


def watch_agent():
    """Pretend agent: works for a few seconds, then asks to run a command."""
    event("running", "Reading the code", type="session_started")
    time.sleep(3)
    return "npm run deploy"


def main():
    command = watch_agent()
    event("waiting_approval", f"Wants to run: {command}",
          request={"kind": "tool", "tool": "shell", "input": command})
    print(f"{SESSION} waits for approval in its own app; watch it in the inbox ...")
    time.sleep(WAIT_S)  # a real pos reports "running" again when the agent's own prompt is answered
    event("running", "Back to work")
    event("ended", "Done", type="session_ended")


if __name__ == "__main__":
    main()
