"""Command-line entry for Feishu Docx/Wiki inspection and approved writeback.

This module owns only argparse routing and exit codes. Document I/O, scanning,
and patch application live in sibling modules so local ``wenlint`` remains
Feishu-independent.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from wenlint import __version__


def main(argv: list[str] | None = None) -> int:
    """Route ``wenlint-feishu`` subcommands and the URL inspect shortcut.

    Until later tasks wire inspect/apply behavior, those routes return exit
    code 2 with a structured ``not_implemented`` error so callers fail closed
    instead of silently doing nothing.

    Args:
        argv: Command-line arguments without the program name. ``None`` uses
            ``sys.argv[1:]``.

    Returns:
        Process exit code. ``--help`` / ``--version`` return 0; unimplemented
        routes return 2.
    """
    args = _parse_args(argv)
    if args.command == "inspect" or args.url is not None:
        return _not_implemented("inspect")
    if args.command == "apply":
        return _not_implemented("apply")
    return _not_implemented("unknown")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse Feishu CLI arguments, including the URL inspect shortcut.

    Args:
        argv: Raw argument list, or ``None`` for ``sys.argv[1:]``.

    Returns:
        Parsed namespace. Shortcut form sets ``command="inspect"`` and
        ``url`` to the document URL.
    """
    parser = argparse.ArgumentParser(
        prog="wenlint-feishu",
        description=(
            "WenLint Feishu adapter: inspect Docx/Wiki documents and apply "
            "approved section patches"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"wenlint-feishu {__version__}",
    )

    # Shortcut: wenlint-feishu <url> --json [--profile PROFILE]
    if argv is None:
        argv = sys.argv[1:]
    argv_list = list(argv)
    if argv_list and not argv_list[0].startswith("-") and argv_list[0] not in {
        "inspect",
        "apply",
    }:
        shortcut = argparse.ArgumentParser(prog="wenlint-feishu", add_help=False)
        shortcut.add_argument("url")
        shortcut.add_argument("--json", action="store_true")
        shortcut.add_argument("--profile", default="general")
        shortcut.add_argument(
            "--version",
            action="version",
            version=f"wenlint-feishu {__version__}",
        )
        shortcut.add_argument("-h", "--help", action="help")
        ns = shortcut.parse_args(argv_list)
        ns.command = "inspect"
        return ns

    sub = parser.add_subparsers(dest="command")

    inspect_p = sub.add_parser("inspect", help="Fetch and scan a Feishu document")
    inspect_p.add_argument("url", help="HTTPS Docx or Wiki URL")
    inspect_p.add_argument("--json", action="store_true", help="Emit JSON on stdout")
    inspect_p.add_argument("--profile", default="general", help="WenLint profile")

    apply_p = sub.add_parser("apply", help="Apply an approved section patch manifest")
    apply_p.add_argument("url", help="HTTPS Docx or Wiki URL")
    apply_p.add_argument(
        "--patch-file",
        required=True,
        help="Approved patch manifest path under the current working directory",
    )
    apply_p.add_argument("--json", action="store_true", help="Emit JSON on stdout")

    return parser.parse_args(argv_list)


def _not_implemented(route: str) -> int:
    """Emit a compact stderr error for routes not yet wired.

    Args:
        route: Logical route name recorded in the structured error.

    Returns:
        Always ``2`` so invalid or unfinished input fails closed.
    """
    payload = {
        "ok": False,
        "kind": "not_implemented",
        "message": f"wenlint-feishu {route} is not implemented yet",
        "retryable": False,
    }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
