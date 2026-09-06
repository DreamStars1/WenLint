"""Packaging and console-script contract for WenLint 0.2."""
from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_declares_supported_python_and_scripts():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["requires-python"] == ">=3.11"
    assert data["project"].get("dependencies") == []
    assert data["project"]["optional-dependencies"]["test"] == ["pytest>=8.4,<10"]
    assert data["project"]["scripts"]["wenlint"] == "wenlint.cli:main"
    assert data["project"]["scripts"]["wenlint-feishu"] == "wenlint.feishu.cli:main"
