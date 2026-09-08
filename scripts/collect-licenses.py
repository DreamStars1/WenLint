"""Collect installed dependency notices for redistribution (a superset of runtime)."""

from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / "build" / "third-party-licenses"
    target.mkdir(parents=True, exist_ok=True)
    inventory = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name", "unknown")
        folder = target / "python" / re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        notices = [
            path for path in (dist.files or [])
            if Path(str(path)).name.lower().startswith(("license", "licence", "copying", "notice"))
        ]
        folder.mkdir(parents=True, exist_ok=True)
        for index, path in enumerate(notices):
            source = Path(dist.locate_file(path))
            if source.is_file():
                shutil.copy2(source, folder / f"{index}-{source.name}")
        metadata = {"name": name, "version": dist.version,
                    "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                    "home_page": dist.metadata.get("Home-page"), "notice_files": len(notices)}
        (folder / "package.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        inventory.append(metadata)
    for notice in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if notice.is_file():
            shutil.copy2(notice, target / "Python-LICENSE.txt")
            break
    frontend = root / "desktop-ui" / "node_modules" / ".pnpm"
    for source in frontend.rglob("*"):
        if source.is_file() and source.name.lower().startswith(("license", "licence", "copying", "notice")):
            destination = target / "javascript" / source.relative_to(frontend)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (target / "README.txt").write_text(
        "Dependency notices from the build environment; includes development/build tools.\n"
        "Each dependency retains its own license. This directory is not a runtime-only SBOM.\n",
        encoding="utf-8",
    )
    print(f"Collected notices for {len(inventory)} Python distributions and installed frontend packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
