from __future__ import annotations

import tomllib
from pathlib import Path

from app import __version__


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert tomllib.loads(pyproject.read_text())["project"]["version"] == __version__
