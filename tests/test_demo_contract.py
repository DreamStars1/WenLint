from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"


def test_demo_bundle_is_complete_and_self_verifying() -> None:
    required = (
        DEMO / "README.md",
        DEMO / "start-demo.ps1",
        DEMO / "review-me.md",
        DEMO / "workspace" / "review-me.md",
        DEMO / "workspace" / "evidence" / "product-baseline.md",
        DEMO / "workspace" / "evidence" / "acceptance-results.txt",
        DEMO / "evidence" / "expected-static-findings.json",
        DEMO / "evidence" / "expected-revision.md",
        DEMO / "evidence" / "semantic-review-checklist.md",
        DEMO / "verify_demo.py",
    )
    assert all(path.is_file() for path in required)
    launcher = (DEMO / "start-demo.ps1").read_text(encoding="utf-8")
    assert "dist-0.5.0-final" not in launcher

    result = subprocess.run(
        [sys.executable, "-S", str(DEMO / "verify_demo.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "DEMO VERIFIED" in result.stdout
