"""A real hub on a free port, for tests that need an HTTP client against it."""

import json
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from sekantor.hub.app import create_app
from sekantor.hub.notify import Notifier
from tests.test_hook import free_port

TOKEN = "tok"
SID = "claude:abc"


class Hub:
    def __init__(self, home, settings=None):
        self.port = free_port()
        self.app = create_app(home=home, port=self.port, token=TOKEN, settings=settings, notifier=Notifier(enabled=False))
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def session(self):
        return self.app.state.store.session(SID)
