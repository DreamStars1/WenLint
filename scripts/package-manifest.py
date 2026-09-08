"""Write a portable checksum and non-secret build provenance beside an archive."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path


def main() -> int:
    archive = Path(sys.argv[1])
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )
    inventory = {
        "artifact": archive.name,
        "sha256": digest,
        "commit": os.environ.get("GITHUB_SHA", "local-build"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "signed_by_publisher": False,
        "packages": dict(sorted(
            (dist.metadata["Name"], dist.version)
            for dist in importlib.metadata.distributions()
            if dist.metadata.get("Name")
        )),
    }
    archive.with_suffix(".build.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
