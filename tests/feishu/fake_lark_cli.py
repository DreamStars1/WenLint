"""In-process fake ``lark-cli`` executable for Feishu adapter contract tests.

The fake records argv arrays and returns fixture JSON without contacting a
real Feishu tenant. Tests point ``LarkClient`` at this script path.

``FAKE_LARK_DIALECT`` selects ``legacy`` (explicit ``--format json``) or
``modern`` (default JSON, no ``--format`` flag).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _dialect() -> str:
    """Return the configured CLI dialect name."""
    value = os.environ.get("FAKE_LARK_DIALECT", "legacy").strip().lower()
    return value if value in {"legacy", "modern"} else "legacy"


def _require_json_args(args: list[str]) -> bool:
    """Validate argv against the selected dialect's JSON flag expectations.

    Args:
        args: Full argv including program name.

    Returns:
        True when argv matches the dialect contract.
    """
    has_format = "--format" in args
    if _dialect() == "legacy":
        if not has_format:
            return False
        try:
            return args[args.index("--format") + 1] == "json"
        except (ValueError, IndexError):
            return False
    return not has_format


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
        if _dialect() == "modern":
            sys.stdout.write(
                "docs +fetch --doc <docx-or-wiki-url> --doc-format xml "
                "--detail full --as user\n"
                "Resolves /wiki/ tokens to the underlying Docx document.\n"
                "Stdout defaults to JSON.\n"
            )
        else:
            sys.stdout.write(
                "docs +fetch --doc <docx-or-wiki-url> --doc-format xml "
                "--detail full --as user --format json\n"
                "Resolves /wiki/ tokens to the underlying Docx document.\n"
            )
        return 0

    if args[1:3] == ["docs", "+update"] and "--help" in args:
        if _dialect() == "modern":
            sys.stdout.write(
                "docs +update --command block_replace --revision-id --block-id "
                "--content --doc-format xml --as user\n"
                "Stdout defaults to JSON.\n"
            )
        else:
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

    if mode == "nonzero_stdout_auth":
        leak = os.environ.get("FAKE_LARK_LEAK", "<p>secret</p>")
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": "auth",
                        "message": leak,
                        "hint": "run lark-cli auth login",
                    },
                }
            )
        )
        return 1

    if mode == "nonzero_stderr_scope":
        leak = os.environ.get("FAKE_LARK_LEAK", "https://example/leak")
        sys.stdout.write("not-json-prelude\n")
        sys.stderr.write(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": "scope",
                        "message": leak,
                        "missing_scopes": ["docs:read"],
                        "hint": "grant docs:read",
                    },
                }
            )
        )
        return 1

    if mode == "nonzero_unstructured":
        leak = os.environ.get("FAKE_LARK_LEAK", "<h1>secret</h1>")
        sys.stdout.write(f"raw failure {leak}\n")
        sys.stderr.write(f"boom {leak}\n")
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

    if mode == "leaky_error":
        leak = os.environ.get("FAKE_LARK_LEAK", "<p>secret</p>")
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "error": {"type": "network", "message": leak},
                }
            )
        )
        return 0

    if mode == "partial_success":
        if not _require_json_args(args):
            sys.stderr.write("dialect argv mismatch\n")
            return 2
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
        if not _require_json_args(args):
            sys.stderr.write("dialect argv mismatch\n")
            return 2
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

    if mode == "ambiguous_content":
        if not _require_json_args(args):
            sys.stderr.write("dialect argv mismatch\n")
            return 2
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "document": {
                            "document_id": "DocToken",
                            "revision_id": 1,
                            "url": "https://acme.feishu.cn/docx/DocToken",
                            "content": '<p id="a">nested</p>',
                        },
                        "content": '<p block-id="a">legacy</p>',
                    },
                }
            )
        )
        return 0

    if mode == "update_stale_revision":
        if not _require_json_args(args):
            sys.stderr.write("dialect argv mismatch\n")
            return 2
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "data": {"result": "success", "revision_id": 1},
                }
            )
        )
        return 0

    if mode == "update_no_warnings":
        if not _require_json_args(args):
            sys.stderr.write("dialect argv mismatch\n")
            return 2
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "data": {"result": "success", "revision_id": 9},
                }
            )
        )
        return 0

    if args[1:3] == ["docs", "+fetch"]:
        if not _require_json_args(args):
            sys.stderr.write("dialect argv mismatch\n")
            return 2
        state_path = os.environ.get("FAKE_LARK_STATE")
        if state_path and Path(state_path).is_file():
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            fetch_count = int(state.get("fetch_count", 0)) + 1
            state["fetch_count"] = fetch_count
            Path(state_path).write_text(json.dumps(state), encoding="utf-8")
            fail_after = state.get("fail_fetch_after")
            if fail_after is not None and fetch_count > int(fail_after):
                sys.stdout.write(
                    json.dumps(
                        {
                            "ok": False,
                            "error": {
                                "type": "network",
                                "message": "scripted fetch network failure",
                            },
                        }
                    )
                )
                return 0
            if _dialect() == "modern":
                document = {
                    "document_id": state.get("document_id", "DocToken"),
                    "revision_id": state["revision_id"],
                    "content": state["content"],
                }
                if state.get("url"):
                    document["url"] = state["url"]
                payload = {"ok": True, "data": {"document": document}}
            else:
                payload = {
                    "ok": True,
                    "data": {
                        "document": {
                            "document_id": state.get("document_id", "DocToken"),
                            "revision_id": state["revision_id"],
                            "url": state.get(
                                "url", "https://acme.feishu.cn/docx/DocToken"
                            ),
                        },
                        "content": state["content"],
                    },
                }
            sys.stdout.write(json.dumps(payload))
            return 0
        fixture_name = (
            "fetch_success_modern.json"
            if _dialect() == "modern"
            else "fetch_success.json"
        )
        payload = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
        sys.stdout.write(json.dumps(payload))
        return 0

    if args[1:3] == ["docs", "+update"]:
        if not _require_json_args(args):
            sys.stderr.write("dialect argv mismatch\n")
            return 2
        state_path = os.environ.get("FAKE_LARK_STATE")
        if state_path and Path(state_path).is_file():
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            try:
                block_id = args[args.index("--block-id") + 1]
                content = args[args.index("--content") + 1]
                revision = int(args[args.index("--revision-id") + 1])
            except (ValueError, IndexError):
                sys.stdout.write(
                    json.dumps(
                        {
                            "ok": False,
                            "error": {"type": "protocol_error", "message": "bad argv"},
                        }
                    )
                )
                return 0
            if revision != state["revision_id"]:
                sys.stdout.write(
                    json.dumps(
                        {
                            "ok": False,
                            "error": {
                                "type": "revision_conflict",
                                "message": "revision conflict",
                            },
                        }
                    )
                )
                return 0
            xml = state["content"]
            pattern = re.compile(
                rf'(<(?:p|h[1-9]|li|blockquote)\b[^>]*(?:block-id|block_id|id)="{re.escape(block_id)}"[^>]*>'
                rf".*?</(?:p|h[1-9]|li|blockquote)>)",
                re.DOTALL,
            )
            if not pattern.search(xml):
                markers = (
                    f'block-id="{block_id}"',
                    f'block_id="{block_id}"',
                    f'id="{block_id}"',
                )
                if not any(marker in xml for marker in markers):
                    sys.stdout.write(
                        json.dumps(
                            {
                                "ok": False,
                                "error": {
                                    "type": "block_missing",
                                    "message": "block not found",
                                },
                            }
                        )
                    )
                    return 0
            updated = pattern.sub(content, xml, count=1)
            if updated == xml:
                originals = state.get("block_xml", {})
                original = originals.get(block_id)
                if original and original in xml:
                    updated = xml.replace(original, content, 1)
                else:
                    for marker in (
                        f'block-id="{block_id}"',
                        f'block_id="{block_id}"',
                        f'id="{block_id}"',
                    ):
                        if marker in xml:
                            start = xml.index(marker)
                            lt = xml.rfind("<", 0, start)
                            updated = xml[:lt] + content + xml[xml.find(">", start) + 1 :]
                            break
            state["content"] = updated
            prior_revision = state["revision_id"]
            state["revision_id"] = revision + 1
            Path(state_path).write_text(json.dumps(state), encoding="utf-8")
            # Optionally echo the pre-write revision to mimic unreliable receipts.
            echoed = state.get("echo_old_revision")
            reported = prior_revision if echoed else state["revision_id"]
            sys.stdout.write(
                json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "result": "success",
                            "revision_id": reported,
                            "warnings": state.get("warnings", []),
                        },
                    }
                )
            )
            return 0
        payload = json.loads(
            (FIXTURES / "update_success.json").read_text(encoding="utf-8")
        )
        sys.stdout.write(json.dumps(payload))
        return 0

    sys.stderr.write("unknown fake command\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
