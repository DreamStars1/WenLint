"""WenLint CLI：像 ESLint 一样检查中文 PRD/论文/报告/Markdown。

用法：
    wenlint <path>                     review
    wenlint <path> --fix               修复预览（不写盘）
    wenlint <path> --fix --apply       修复并写盘（先备份 .bak）
    wenlint <path> --json              JSON 输出
    wenlint <path> --profile academic  场景 profile
    wenlint <path> --fail-level warning  存在 >= 该级别时 exit 1（CI）
"""
import argparse
import json
import os
import sys

from . import __version__
from .engine import scan_text, fix_text
from .profiles import PROFILES

LEVEL_RANK = {"error": 3, "warning": 2, "suggestion": 1}


def collect_files(path):
    if os.path.isfile(path):
        return [path]
    files = []
    for root, _, fs in os.walk(path):
        for f in fs:
            if f.endswith((".md", ".txt", ".rst", ".markdown")):
                files.append(os.path.join(root, f))
    return sorted(files)


def format_line(fp, f):
    msg = f["message"]
    if f["match"]:
        msg = f"{msg} 「{f['match']}」" if "「" not in msg else msg
    return (f"{fp}:{f['line']}:{f['col']}  "
            f"{f['rule_id']:<5} {f['severity']:<10} {f['category']}  {msg}")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="wenlint",
        description="WenLint：中文写作静态检查器（规则 ID + profile + 安全 fix）",
    )
    p.add_argument("path", nargs="+", help="文件或目录（可多个）")
    p.add_argument("--version", action="version", version=f"wenlint {__version__}")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--fix", action="store_true", help="修复模式：自动删除套话，显示 diff")
    p.add_argument("--apply", action="store_true", help="与 --fix 连用：写回文件（先备份 .bak）")
    p.add_argument("--profile", choices=sorted(PROFILES), default="general",
                   help="场景 profile：academic/product/formal/general")
    p.add_argument("--fail-level", choices=["error", "warning", "suggestion"],
                   default=None, help="存在 >= 该级别的命中时 exit 1（默认不失败）")
    p.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = p.parse_args(argv)

    files = []
    for p in args.path:
        files += collect_files(p)
    files = sorted(set(files))
    if not files:
        print(f"!! 未找到可检查文件: {args.path}", file=sys.stderr)
        return 2

    # ---------- fix 模式 ----------
    if args.fix:
        fixed_map = {}
        for fp in files:
            try:
                raw = open(fp, encoding="utf-8").read()
            except OSError as e:
                print(f"!! 无法读取 {fp}: {e}", file=sys.stderr)
                continue
            fixed, changes = fix_text(raw, profile=args.profile)
            fixed_map[fp] = fixed
            if not changes:
                print(f"✅ {fp}: 无可自动修复项")
                continue
            print(f"--- {fp}: {len(changes)} 处自动修复 ---")
            raw_lines = raw.split("\n")
            fixed_lines = fixed.split("\n")
            seen = set()
            for line_no, rid, note in changes:
                if line_no in seen:
                    continue
                seen.add(line_no)
                old = raw_lines[line_no - 1].strip()
                new = fixed_lines[line_no - 1].strip()
                print(f"  L{line_no} [{rid}] {note}")
                print(f"    - {old}")
                print(f"    + {new}")
            if args.apply:
                backup = fp + ".bak"
                with open(backup, "w", encoding="utf-8") as bf:
                    bf.write(raw)
                with open(fp, "w", encoding="utf-8") as wf:
                    wf.write(fixed)
                print(f"  ✍️ 已写回 {fp}（备份 {backup}）")
        # 修复后剩余：扫描修复后的文本（v0.1 修复点：不再重扫磁盘原文件）
        print("\n=== 修复后剩余（需人工判断）===")
        remaining = []
        for fp in files:
            if fp in fixed_map:
                findings = scan_text(fixed_map[fp], profile=args.profile)
            else:
                continue
            remaining += [(fp, f) for f in findings]
        if remaining:
            for fp, f in remaining:
                if not args.quiet:
                    print(format_line(fp, f))
        else:
            print("✅ 全部干净")
        worst = max((LEVEL_RANK[f["severity"]] for _, f in remaining), default=0)
        if args.fail_level and worst >= LEVEL_RANK[args.fail_level]:
            return 1
        return 0

    # ---------- review 模式 ----------
    results = []
    total = 0
    for fp in files:
        try:
            text = open(fp, encoding="utf-8").read()
        except OSError as e:
            print(f"!! 无法读取 {fp}: {e}", file=sys.stderr)
            continue
        findings = scan_text(text, profile=args.profile)
        total += len(findings)
        results.append((fp, findings))

    if args.json:
        out = [{"file": fp, **f} for fp, findings in results for f in findings]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for fp, findings in results:
            for f in findings:
                if not args.quiet:
                    print(format_line(fp, f))
        if total == 0:
            print("✅ 未发现坏味")
        else:
            per = "  ".join(f"{os.path.basename(fp)}: {len(h)}"
                            for fp, h in results if h)
            print(f"\n✖ {total} 处（{per}）")

    if args.fail_level:
        worst = max((LEVEL_RANK[f["severity"]]
                     for _, fs in results for f in fs), default=0)
        return 1 if worst >= LEVEL_RANK[args.fail_level] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
