"""WenLint CLI：像 ESLint 一样检查中文 PRD/论文/报告/Markdown。

架构（分层职责）：
    main()          极轻路由：解析参数 → 分发 fix/review 两个入口
    _run_review()   业务步骤编排（高层）：加载 → 扫描 → 输出，不含实现细节
    _run_fix()      业务步骤编排（高层）：加载 → 修复 → 差异 → 剩余扫描
    _load/_scan/_emit 等：具体实现层（每个函数只做一件事，抽象层次一致）

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

LEVEL_RANK = {"error": 3, "warning": 2, "suggestion": 1, "candidate": 0}
DOC_EXTS = (".md", ".txt", ".rst", ".markdown")


# ============ 路由层 ============

def main(argv=None):
    args = _parse_args(argv)
    files = _collect_files(args.path)
    if not files:
        print(f"!! 未找到可检查文件: {args.path}", file=sys.stderr)
        return 2
    if args.fix:
        return _run_fix(files, args)
    return _run_review(files, args)


# ============ 参数与输入 ============

def _parse_args(argv):
    p = argparse.ArgumentParser(
        prog="wenlint",
        description="WenLint：中文写作静态检查器（规则 ID + profile + 安全 fix）",
    )
    p.add_argument("path", nargs="+", help="文件或目录（可多个）")
    p.add_argument("--version", action="version", version=f"wenlint {__version__}")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--fix", action="store_true", help="修复模式：自动删除套话，显示 diff")
    p.add_argument("--apply", action="store_true",
                   help="与 --fix 连用：写回文件（先备份 .bak）")
    p.add_argument("--profile", choices=sorted(PROFILES), default="general",
                   help="场景 profile：academic/product/formal/general")
    p.add_argument("--fail-level", choices=["error", "warning", "suggestion"],
                   default=None, help="存在 >= 该级别的命中时 exit 1（默认不失败）")
    p.add_argument("--quiet", action="store_true", help="只输出汇总")
    return p.parse_args(argv)


def _effective_profile(fp, requested):
    """文件名 SKILL.md → instruction 阈值（长句 50），其他文件 → 请求的 profile。
    用户显式 --profile 时尊重用户选择。"""
    if requested != "general":
        return requested
    if fp.endswith("SKILL.md"):
        return "instruction"
    return requested


def _collect_files(paths):
    """多路径收集：文件直接收，目录递归收支持的扩展名。"""
    files = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
        else:
            for root, _, fs in os.walk(p):
                files += [os.path.join(root, f) for f in fs
                          if f.endswith(DOC_EXTS)]
    return sorted(set(files))


def _load_texts(files):
    """读取文件 → {fp: text}（跳过不可读文件并告警）。"""
    texts = {}
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as fh:
                texts[fp] = fh.read()
        except OSError as e:
            print(f"!! 无法读取 {fp}: {e}", file=sys.stderr)
    return texts


def _display_path(fp):
    return os.path.relpath(fp) if os.path.isabs(fp) else fp


# ============ review 入口（业务步骤编排）============

def _run_review(files, args):
    texts = _load_texts(files)
    results = _scan_all(texts, args.profile)
    findings = [f for _, fs in results for f in fs]
    if args.json:
        _emit_json(results, texts)
    elif findings:
        for fp, fs in results:
            for f in fs:
                if not args.quiet:
                    print(_format_finding(fp, f))
        _emit_summary(results)
    else:
        print("✅ 未发现坏味")
    return _exit_code(findings, args.fail_level)


def _scan_all(texts, profile):
    """{fp: text} → [(fp, findings)]，按文件逐个扫描。"""
    results = []
    for fp, text in texts.items():
        results.append((fp, scan_text(text, profile=_effective_profile(fp, profile),
                                      filename=fp)))
    return results


def _emit_json(results, texts):
    out = []
    for fp, findings in results:
        lines = texts[fp].split("\n")
        for f in findings:
            ln = f["line"]
            ctx = {
                "before": lines[ln - 2] if ln >= 2 else None,
                "line": lines[ln - 1] if 1 <= ln <= len(lines) else None,
                "after": lines[ln] if ln < len(lines) else None,
            }
            out.append({"file": fp, **f, "context": ctx})
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _emit_summary(results):
    per = "  ".join(f"{_display_path(fp)}: {len(h)}" for fp, h in results if h)
    total = sum(len(h) for _, h in results)
    print(f"\n✖ {total} 处（{per}）")


def _format_finding(fp, f):
    msg = f["message"]
    if f["match"]:
        msg = f"{msg} 「{f['match']}」" if "「" not in msg else msg
    return (f"{_display_path(fp)}:{f['line']}:{f['col']}  "
            f"{f['rule_id']:<5} {f['severity']:<10} {f['category']}  {msg}")


def _exit_code(findings, fail_level):
    """--fail-level 时：存在 >= 该级别的命中 → 1。"""
    if not fail_level:
        return 0
    worst = max((LEVEL_RANK[f["severity"]] for f in findings), default=0)
    return 1 if worst >= LEVEL_RANK[fail_level] else 0


# ============ fix 入口（业务步骤编排）============

def _run_fix(files, args):
    texts = _load_texts(files)
    fixed_map, diffs = _fix_all(texts, args.profile)
    if args.apply:
        _write_back(files, texts, fixed_map)
    _print_fix_diff(diffs)
    remaining = _scan_remaining(fixed_map, args.profile)
    _print_remaining(remaining, args.quiet)
    return _exit_code([f for _, fs in remaining for f in fs], args.fail_level)


def _fix_all(texts, profile):
    """{fp: text} → (fixed_map, [(fp, changes)])。"""
    fixed_map, diffs = {}, []
    for fp, raw in texts.items():
        fixed, changes = fix_text(raw, profile=_effective_profile(fp, profile))
        fixed_map[fp] = fixed
        if changes:
            diffs.append((fp, raw, fixed, changes))
    return fixed_map, diffs


def _write_back(files, texts, fixed_map):
    """备份原文件 + 写回修复文本。"""
    for fp in files:
        if fp not in fixed_map:
            continue
        with open(fp + ".bak", "w", encoding="utf-8") as bf:
            bf.write(texts[fp])
        with open(fp, "w", encoding="utf-8") as wf:
            wf.write(fixed_map[fp])
        print(f"  ✍️ 已写回 {_display_path(fp)}（备份 .bak）")


def _print_fix_diff(diffs):
    for fp, raw, fixed, changes in diffs:
        raw_lines, fixed_lines = raw.split("\n"), fixed.split("\n")
        print(f"--- {_display_path(fp)}: {len(changes)} 处自动修复 ---")
        for line_no, rid, note in changes:
            print(f"  L{line_no} [{rid}] {note}")
            print(f"    - {raw_lines[line_no - 1].strip()}")
            print(f"    + {fixed_lines[line_no - 1].strip()}")


def _scan_remaining(fixed_map, profile):
    """修复后剩余：扫描修复后的文本（而非磁盘原文件）。"""
    return [(fp, scan_text(fixed, profile=_effective_profile(fp, profile),
                           filename=fp))
            for fp, fixed in fixed_map.items()]


def _print_remaining(remaining, quiet):
    print("\n=== 修复后剩余（需人工判断）===")
    if not remaining:
        print("✅ 全部干净")
        return
    for fp, fs in remaining:
        for f in fs:
            if not quiet:
                print(_format_finding(fp, f))


if __name__ == "__main__":
    sys.exit(main())
