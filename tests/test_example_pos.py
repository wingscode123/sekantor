"""The example pos in examples/ must keep working against the real hub."""

import os
import subprocess
import sys
import time
from pathlib import Path

from tests.live_hub import TOKEN, Hub

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "pos_minimal.py"


def test_example_pos_reports_a_wait_and_then_ends(tmp_path):
    (tmp_path / "token").write_text(TOKEN)
    with Hub(tmp_path) as hub:
        env = {**os.environ, "RONDA_HOME": str(tmp_path), "RONDA_URL": f"http://127.0.0.1:{hub.port}",
               "EXAMPLE_WAIT_S": "1"}
        p = subprocess.Popen([sys.executable, str(EXAMPLE)], env=env, stdout=subprocess.PIPE, text=True)
        waiting = []
        for _ in range(200):
            waiting = [s for s in hub.app.state.store.sessions() if s.status.value == "waiting_approval"]
            if waiting:
                break
            time.sleep(0.1)
        assert waiting and waiting[0].source == "example" and waiting[0].request.input == "npm run deploy"
        p.communicate(timeout=20)
        assert p.returncode == 0
        assert hub.app.state.store.session(waiting[0].session_id).status.value == "ended"
