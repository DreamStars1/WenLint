from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_entrypoint_and_build_extra_are_declared() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["wenlint-desktop"] == "wenlint.desktop:main"
    assert "pywebview" in " ".join(
        data["project"]["optional-dependencies"]["desktop"]
    ).lower()
    assert "pyinstaller" in " ".join(
        data["project"]["optional-dependencies"]["desktop-build"]
    ).lower()


def test_windows_builder_and_ci_use_workspace_local_pytest_temp() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )
    assert "--basetemp=.pytest-basetemp-ci" in workflow
    assert (ROOT / "scripts" / "build-windows.ps1").is_file()
    assert (ROOT / ".github" / "workflows" / "build-windows.yml").is_file()


def test_vue_desktop_exists_and_does_not_persist_credentials() -> None:
    source = (ROOT / "wenlint" / "desktop.py").read_text(encoding="utf-8")
    vue_source = (ROOT / "desktop-ui" / "src" / "App.vue").read_text(encoding="utf-8")
    assert (ROOT / "desktop-ui" / "package.json").is_file()
    assert (ROOT / "wenlint" / "desktop_ui" / "index.html").is_file()
    assert "window.pywebview" in vue_source and ".api" in vue_source
    forbidden = ("localStorage", "sessionStorage", "keyring", "winreg")
    assert all(token not in source + vue_source for token in forbidden)
