import subprocess

import pytest


def test_guard_blocks_real_service_tools():
    from sekantor import service

    with pytest.raises(AssertionError):
        service.run([["schtasks", "/Query"]])
    with pytest.raises(AssertionError, match="schtasks"):
        subprocess.run(["schtasks", "/Query"])
