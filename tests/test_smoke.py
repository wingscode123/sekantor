import tomllib
from pathlib import Path

import sekantor


def test_version_matches_pyproject():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert sekantor.__version__ == pyproject["project"]["version"]
