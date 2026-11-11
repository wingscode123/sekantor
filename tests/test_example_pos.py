"""The example pos in examples/ must keep working against the real hub."""

import os
import subprocess
import sys
import time
from pathlib import Path

from ronda.config import Settings
from tests.test_hook_actions import TOKEN, Hub

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "pos_minimal.py"


def test_example_pos_round_trip(tmp_path):
    (tmp_path / "token").write_text(TOKEN)
    with Hub(tmp_path, Settings()) as hub:
        env = {**os.environ, "RONDA_HOME": str(tmp_path), "RONDA_URL": f"http://127.0.0.1:{hub.port}"}
        p = subprocess.Popen([sys.executable, str(EXAMPLE)], env=env, stdout=subprocess.PIPE, text=True)
        for _ in range(200):
            waiting = [s for s in hub.app.state.store.sessions() if s.status.value == "waiting_approval"]
            if waiting:
                break
            time.sleep(0.1)
        s = waiting[0]
        assert s.source == "example" and s.capabilities == ["approve", "deny"]
        code, _ = hub.call("POST", f"/v1/sessions/{s.session_id}/actions", {"type": "approve"})
        assert code == 202
        out, _ = p.communicate(timeout=20)
        assert p.returncode == 0 and "approved, running it" in out
        assert hub.app.state.store.session(s.session_id).status.value == "ended"
