"""Command-line entry for Feishu Docx/Wiki inspection and approved writeback.

This module owns only argparse routing, JSON emission, and exit codes. Document
I/O, scanning, and patch application live in sibling modules so local
``wenlint`` remains Feishu-independent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from wenlint import __version__
from wenlint.feishu.document import DocumentRefError, parse_document_ref
from wenlint.feishu.inspection import inspect_document
from wenlint.feishu.lark import LarkCliError, LarkClient
from wenlint.feishu.patches import (
    ManifestError,
    PatchValidationError,
    apply_approved_section,
    load_manifest,
)
from wenlint.feishu.projection import XmlSafetyError
from wenlint.feishu.sections import SectionError
from wenlint.profiles import PROFILES

_LEVEL_RANK = {"error": 3, "warning": 2, "suggestion": 1, "candidate": 0}


def main(argv: list[str] | None = None) -> int:
    """Route ``wenlint-feishu`` subcommands and the URL inspect shortcut.

    Args:
        argv: Command-line arguments without the program name. ``None`` uses
            ``sys.argv[1:]``.

    Returns:
        Process exit code from the Feishu CLI contract.
    """
    args = _parse_args(argv)
    if args.command == "apply":
        return _cmd_apply(args)
    if args.command == "inspect":
        return _cmd_inspect(args)
    return _emit_error("invalid_input", "unknown command", retryable=False, exit_code=2)


def _cmd_apply(args: argparse.Namespace) -> int:
    """Apply an approved section patch manifest with fail-closed writeback.

    Args:
        args: Parsed arguments containing ``url`` and ``patch_file``.

    Returns:
        Exit code 0/2/3/4/5 per the Feishu CLI contract.
    """
    try:
        ref = parse_document_ref(args.url)
        client = LarkClient()
        client.probe()
        # Resolve document identity before comparing the manifest document_id.
        fetched = client.fetch(ref)
        plan = load_manifest(Path(args.patch_file), fetched.ref)
        result = apply_approved_section(client, fetched.ref, plan)
    except DocumentRefError as exc:
        return _emit_error(exc.kind, str(exc), retryable=False, exit_code=2)
    except ManifestError as exc:
        return _emit_error(exc.kind, str(exc), retryable=False, exit_code=2)
    except PatchValidationError as exc:
        return _emit_error(exc.kind, str(exc), retryable=False, exit_code=2)
    except SectionError as exc:
        return _emit_error(exc.kind, str(exc), retryable=False, exit_code=4)
    except XmlSafetyError as exc:
        return _emit_error(exc.kind, str(exc), retryable=False, exit_code=2)
    except LarkCliError as exc:
        return _emit_error(
            exc.kind,
            exc.message,
            retryable=exc.retryable,
            exit_code=3,
            details=exc.details,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _emit_error(
            "invalid_response",
            "fetch or apply payload failed schema validation",
            retryable=False,
            exit_code=3,
            details={"hint": type(exc).__name__},
        )

    print(json.dumps(result.to_dict(), ensure_ascii=False))
    if result.status == "success":
        return 0
    if result.status == "conflict":
        return 4
    return 5


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Run read-only inspection for a Docx/Wiki URL.

    Args:
        args: Parsed arguments containing ``url`` and optional ``profile``.

    Returns:
        Exit code 0 on success, 1 when ``--fail-level`` trips, or a mapped failure.
    """
    try:
        ref = parse_document_ref(args.url)
        client = LarkClient()
        client.probe()
        report = inspect_document(client, ref, profile=getattr(args, "profile", "general"))
    except DocumentRefError as exc:
        return _emit_error(exc.kind, str(exc), retryable=False, exit_code=2)
    except XmlSafetyError as exc:
        return _emit_error(exc.kind, str(exc), retryable=False, exit_code=2)
    except LarkCliError as exc:
        return _emit_error(
            exc.kind,
            exc.message,
            retryable=exc.retryable,
            exit_code=3,
            details=exc.details,
        )
    except FileNotFoundError as exc:
        return _emit_error(
            "missing_executable",
            str(exc),
            retryable=False,
            exit_code=3,
        )

    payload = report.to_dict()
    print(json.dumps(payload, ensure_ascii=False))
    return _inspect_exit_code(payload.get("findings") or [], getattr(args, "fail_level", None))


def _inspect_exit_code(findings: list, fail_level: str | None) -> int:
    """Map inspect findings to exit 0 or 1 when a fail level is configured.

    Args:
        findings: Serialized finding list from the inspection report.
        fail_level: Optional severity gate.

    Returns:
        ``1`` when any finding meets the gate; otherwise ``0``.
    """
    if not fail_level:
        return 0
    threshold = _LEVEL_RANK[fail_level]
    for finding in findings:
        severity = str(finding.get("severity") or finding.get("type") or "suggestion")
        if _LEVEL_RANK.get(severity, 0) >= threshold:
            return 1
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse Feishu CLI arguments, including the URL inspect shortcut.

    Args:
        argv: Raw argument list, or ``None`` for ``sys.argv[1:]``.

    Returns:
        Parsed namespace. Shortcut form sets ``command="inspect"``.
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
        shortcut.add_argument(
            "--profile",
            default="general",
            choices=sorted(PROFILES),
            help="WenLint profile",
        )
        shortcut.add_argument(
            "--fail-level",
            choices=["error", "warning", "suggestion"],
            default=None,
            help="Exit 1 when findings meet or exceed this severity",
        )
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
    inspect_p.add_argument(
        "--profile",
        default="general",
        choices=sorted(PROFILES),
        help="WenLint profile",
    )
    inspect_p.add_argument(
        "--fail-level",
        choices=["error", "warning", "suggestion"],
        default=None,
        help="Exit 1 when findings meet or exceed this severity",
    )

    apply_p = sub.add_parser("apply", help="Apply an approved section patch manifest")
    apply_p.add_argument("url", help="HTTPS Docx or Wiki URL")
    apply_p.add_argument(
        "--patch-file",
        required=True,
        help="Approved patch manifest path under the current working directory",
    )
    apply_p.add_argument("--json", action="store_true", help="Emit JSON on stdout")

    return parser.parse_args(argv_list)


def _emit_error(
    kind: str,
    message: str,
    *,
    retryable: bool,
    exit_code: int,
    details: dict | None = None,
) -> int:
    """Print a compact stderr JSON error without document bodies.

    Args:
        kind: Stable error classifier.
        message: Human-readable explanation.
        retryable: Whether a later retry may succeed.
        exit_code: Process exit code to return.
        details: Optional safe structured extras.

    Returns:
        The provided ``exit_code``.
    """
    payload = {
        "ok": False,
        "kind": kind,
        "message": message,
        "retryable": retryable,
    }
    if details:
        for key in ("missing_scopes", "hint", "version", "missing_capabilities"):
            if key in details:
                payload[key] = details[key]
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
