"""本地四分类反馈记录（KEEP / REWRITE / VERIFY / ASK）。

纯本地 JSONL，无网络、无遥测。供规则收敛统计（KEEP 率）使用。
与主 CLI 独立，保持向后兼容。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone

DECISIONS = ("KEEP", "REWRITE", "VERIFY", "ASK")
SCHEMA_VERSION = 1
DEFAULT_OUTPUT = os.path.join(".wenlint", "feedback.jsonl")


def main(argv=None):
    """反馈 CLI 入口。

    Args:
        argv: 参数列表；None 时用 sys.argv[1:]。

    Returns:
        int：0 成功 / 2 参数或校验失败。
    """
    args = _parse_args(argv)
    if args.command == "record":
        return _cmd_record(args)
    if args.command == "stats":
        return _cmd_stats(args)
    return 2


def _parse_args(argv):
    """Parse feedback record and statistics arguments.

    Args:
        argv: Command-line arguments without the program name.

    Returns:
        Parsed argument namespace.
    """
    p = argparse.ArgumentParser(
        prog="wenlint-feedback",
        description="WenLint 本地反馈记录（KEEP/REWRITE/VERIFY/ASK，无网络）",
    )
    sub = p.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="追加一条本地反馈记录")
    rec.add_argument("--decision", required=True, help="KEEP/REWRITE/VERIFY/ASK")
    rec.add_argument("--rule", required=True, help="规则 ID，如 H002")
    rec.add_argument("--file", required=True, help="命中文件路径")
    rec.add_argument("--line", required=True, type=int, help="命中行（1-based）")
    rec.add_argument("--column", required=True, type=int, help="命中列（1-based）")
    rec.add_argument("--text", default="", help="命中文本")
    rec.add_argument("--reason", default="", help="判定理由")
    rec.add_argument("--profile", default="", help="当时使用的 profile")
    rec.add_argument("--output", default=DEFAULT_OUTPUT,
                     help=f"JSONL 输出路径（默认 {DEFAULT_OUTPUT}）")

    st = sub.add_parser("stats", help="汇总本地反馈（按规则 KEEP 率）")
    st.add_argument("--input", required=True, help="JSONL 输入路径")
    st.add_argument("--json", action="store_true", help="JSON 输出")

    return p.parse_args(argv)


def _cmd_record(args):
    """Validate and append one feedback record to a local JSONL file.

    Args:
        args: Parsed ``record`` command arguments.

    Returns:
        ``0`` on success or ``2`` when validation fails.
    """
    decision = (args.decision or "").strip().upper()
    if decision not in DECISIONS:
        print(
            f"!! 无效 decision: {args.decision!r}（允许: {', '.join(DECISIONS)}）",
            file=sys.stderr,
        )
        return 2
    if args.line < 1 or args.column < 1:
        print("!! line/column 须为正整数", file=sys.stderr)
        return 2

    record = {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "rule": args.rule,
        "file": args.file,
        "line": args.line,
        "column": args.column,
        "text": args.text,
        "reason": args.reason,
        "profile": args.profile,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    validation_error = _record_validation_error(record)
    if validation_error:
        print(f"!! 无效反馈记录: {validation_error}", file=sys.stderr)
        return 2

    out_path = args.output
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(json.dumps({"ok": True, "output": out_path}, ensure_ascii=False))
    return 0


def _cmd_stats(args):
    """Validate local feedback records and print per-rule statistics.

    Args:
        args: Parsed ``stats`` command arguments.

    Returns:
        ``0`` on success or ``2`` for unreadable or invalid input.
    """
    path = args.input
    try:
        with open(path, encoding="utf-8") as fh:
            lines = list(enumerate(fh, 1))
    except OSError as e:
        print(f"!! 无法读取 {path}: {e}", file=sys.stderr)
        return 2

    by_rule = {}
    total = 0
    for line_number, raw_line in lines:
        ln = raw_line.strip()
        if not ln:
            continue
        try:
            row = json.loads(ln)
        except json.JSONDecodeError as exc:
            print(f"!! {path}:{line_number}: JSON 无效: {exc.msg}", file=sys.stderr)
            return 2
        validation_error = _record_validation_error(row)
        if validation_error:
            print(
                f"!! {path}:{line_number}: 反馈记录无效: {validation_error}",
                file=sys.stderr,
            )
            return 2
        decision = row["decision"]
        rule = row["rule"]
        total += 1
        slot = by_rule.setdefault(rule, {
            "total": 0,
            "decisions": {d: 0 for d in DECISIONS},
        })
        slot["total"] += 1
        slot["decisions"][decision] += 1

    for slot in by_rule.values():
        t = slot["total"]
        slot["keep_rate"] = (slot["decisions"]["KEEP"] / t) if t else 0.0

    stats = {"total": total, "by_rule": by_rule}
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"total: {total}")
        for rule, slot in sorted(by_rule.items()):
            print(
                f"  {rule}: total={slot['total']} "
                f"KEEP={slot['decisions']['KEEP']} "
                f"keep_rate={slot['keep_rate']:.2f}"
            )
    return 0


def _record_validation_error(record):
    """Validate one feedback record.

    Args:
        record: Decoded JSON value or newly constructed record.

    Returns:
        A validation message, or ``None`` when the record is valid.
    """
    if not isinstance(record, Mapping):
        return "JSON 行必须是对象"
    if record.get("schema_version") != SCHEMA_VERSION:
        return f"schema_version 必须为 {SCHEMA_VERSION}"
    if record.get("decision") not in DECISIONS:
        return f"decision 必须是 {', '.join(DECISIONS)} 之一"
    for field in ("rule", "file"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"{field} 必须是非空字符串"
    for field in ("line", "column"):
        value = record.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return f"{field} 必须是正整数"
    for field in ("text", "reason", "profile", "recorded_at"):
        if not isinstance(record.get(field), str):
            return f"{field} 必须是字符串"
    return None


if __name__ == "__main__":
    sys.exit(main())
