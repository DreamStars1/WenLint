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
        payload = json.loads(
            (FIXTURES / "fetch_success.json").read_text(encoding="utf-8")
        )
        sys.stdout.write(json.dumps(payload))
        return 0

    if args[1:3] == ["docs", "+update"]:
        state_path = os.environ.get("FAKE_LARK_STATE")
        if state_path and Path(state_path).is_file():
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            # Parse argv for block id, content, and revision.
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
            # Naive block replace by block-id attribute.
            import re

            pattern = re.compile(
                rf'(<(?:p|h[1-9]|li|blockquote)\b[^>]*block-id="{re.escape(block_id)}"[^>]*>.*?</(?:p|h[1-9]|li|blockquote)>)',
                re.DOTALL,
            )
            if not pattern.search(xml):
                # Fall back to replacing a self-contained content argument as the
                # sole matching block serialization used by tests.
                marker = f'block-id="{block_id}"'
                if marker not in xml:
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
            if updated == xml and f'block-id="{block_id}"' in xml:
                # ElementTree serialization may differ; splice by marker window.
                start = xml.index(f'block-id="{block_id}"')
                # Find element start before attribute.
                lt = xml.rfind("<", 0, start)
                # Find matching close tag roughly by next sibling start after end tag.
                # Prefer exact content replacement when the original element string
                # can be recovered from a prior fetch snapshot stored in state.
                originals = state.get("block_xml", {})
                original = originals.get(block_id)
                if original and original in xml:
                    updated = xml.replace(original, content, 1)
                else:
                    updated = xml[:lt] + content + xml[xml.find(">", start) + 1 :]
                    # This fallback is intentionally imperfect; stateful tests
                    # should supply block_xml snapshots.
            state["content"] = updated
            state["revision_id"] = revision + 1
            Path(state_path).write_text(json.dumps(state), encoding="utf-8")
            sys.stdout.write(
                json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "result": "success",
                            "revision_id": state["revision_id"],
                            "warnings": [],
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
