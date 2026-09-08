"""Verify the deterministic parts of the WenLint desktop demo bundle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wenlint.scanner import scan_text
from wenlint.workspace import WorkspaceSession


DEMO_ROOT = Path(__file__).resolve().parent
SOURCE = DEMO_ROOT / "review-me.md"
WORKSPACE_ROOT = DEMO_ROOT / "workspace"
WORKSPACE_SOURCE = WORKSPACE_ROOT / "review-me.md"
EXPECTED = DEMO_ROOT / "evidence" / "expected-static-findings.json"
REFERENCE_REVISION = DEMO_ROOT / "evidence" / "expected-revision.md"


def finding_signature(finding: dict[str, object]) -> dict[str, object]:
    """Return the stable fields used by the checked-in demo snapshot."""

    return {
        "rule_id": finding["rule_id"],
        "line": finding["line"],
        "col": finding["col"],
        "match": finding["match"],
    }


def main() -> int:
    source_bytes = SOURCE.read_bytes()
    if source_bytes != WORKSPACE_SOURCE.read_bytes():
        print("DEMO INVALID: review-me.md differs from the workspace copy")
        return 1

    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    expected_hash = str(expected.get("source_sha256", "")).lower()
    if source_hash != expected_hash:
        print("DEMO INVALID: review document hash does not match the snapshot")
        return 1

    findings = scan_text(
        source_bytes.decode("utf-8"),
        profile=expected.get("profile", "product"),
        filename=SOURCE.name,
    )
    actual = [finding_signature(item) for item in findings]
    if actual != expected.get("findings"):
        print("DEMO INVALID: static findings differ from the expected snapshot")
        print(json.dumps(actual, ensure_ascii=False, indent=2))
        return 1

    reference_findings = scan_text(
        REFERENCE_REVISION.read_text(encoding="utf-8"),
        profile="product",
        filename=REFERENCE_REVISION.name,
    )
    if reference_findings:
        print("DEMO INVALID: reference revision does not pass local checks")
        return 1

    workspace = WorkspaceSession(WORKSPACE_ROOT)
    indexed_paths = {str(item["path"]) for item in workspace.index()}
    required_paths = {
        "review-me.md",
        "evidence/product-baseline.md",
        "evidence/acceptance-results.txt",
    }
    if not required_paths.issubset(indexed_paths):
        print("DEMO INVALID: workspace index is incomplete")
        return 1

    print(
        f"DEMO VERIFIED: {len(actual)} static findings; "
        f"{len(indexed_paths)} workspace files; clean reference revision"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
