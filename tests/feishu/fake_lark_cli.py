"""In-process fake ``lark-cli`` executable for Feishu adapter contract tests.

The fake records argv arrays and returns fixture JSON without contacting a
real Feishu tenant. Tests point ``LarkClient`` at this script path.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def main(argv: list[str] | None = None) -> int:
    """Emulate a minimal subset of ``lark-cli`` for unit tests.

    Args:
        argv: Argument vector including the program name.

    Returns:
        Process exit code matching the scripted scenario.
    """
    args = list(sys.argv if argv is None else argv)
    mode = os.environ.get("FAKE_LARK_MODE", "success")
    record_path = os.environ.get("FAKE_LARK_RECORD")
    if record_path:
        Path(record_path).write_text(json.dumps(args[1:]), encoding="utf-8")

    if mode == "missing":
        return 127

    if len(args) == 2 and args[1] == "--version":
        sys.stdout.write(os.environ.get("FAKE_LARK_VERSION", "lark-cli fake 1.0.0\n"))
        return 0

    if args[1:3] == ["docs", "+fetch"] and "--help" in args:
        sys.stdout.write(
            "docs +fetch --doc <docx-or-wiki-url> --doc-format xml "
            "--detail full --as user --format json\n"
            "Resolves /wiki/ tokens to the underlying Docx document.\n"
        )
        return 0

    if args[1:3] == ["docs", "+update"] and "--help" in args:
        sys.stdout.write(
            "docs +update --command block_replace --revision-id --block-id "
            "--content --doc-format xml --as user --format json\n"
        )
        return 0

    if mode == "sleep":
        time.sleep(float(os.environ.get("FAKE_LARK_SLEEP", "5")))
        return 0

    if mode == "huge_stdout":
        sys.stdout.write("x" * (21 * 1024 * 1024))
        return 0

    if mode == "huge_stderr":
        sys.stderr.write("y" * (2 * 1024 * 1024))
        return 1

    if mode == "nonzero":
        sys.stderr.write("boom\n")
        return 1

    if mode == "bad_json":
        sys.stdout.write("{not-json")
        return 0

    if mode == "ok_false":
        sys.stdout.write(json.dumps({"ok": False, "error": {"type": "network"}}))
        return 0

    if mode == "auth":
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": "auth",
                        "message": "not logged in",
                        "hint": "run lark-cli auth login",
                    },
                }
            )
        )
        return 0

    if mode == "scope":
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": "scope",
                        "missing_scopes": ["docs:read"],
                        "hint": "grant docs:read",
                    },
                }
            )
        )
        return 0

    if mode == "permission":
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "error": {"type": "permission", "message": "forbidden"},
                }
            )
        )
        return 0

    if mode == "partial_success":
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "data": {"result": "partial_success", "revision_id": 10},
                }
            )
        )
        return 0

    if mode == "missing_revision":
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "document": {"document_id": "DocToken"},
                        "content": "<p>x</p>",
                    },
                }
            )
        )
        return 0

    if args[1:3] == ["docs", "+fetch"]:
        payload = json.loads(
            (FIXTURES / "fetch_success.json").read_text(encoding="utf-8")
        )
        sys.stdout.write(json.dumps(payload))
        return 0

    if args[1:3] == ["docs", "+update"]:
        payload = json.loads(
            (FIXTURES / "update_success.json").read_text(encoding="utf-8")
        )
        sys.stdout.write(json.dumps(payload))
        return 0

    sys.stderr.write("unknown fake command\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
