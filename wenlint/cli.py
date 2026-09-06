"""WenLint CLI：像 ESLint 一样检查中文 PRD/论文/报告/Markdown。

架构（分层职责）：
    main()          极轻路由：解析参数 → review
    _run_review()   业务步骤编排（高层）：加载 → 扫描 → 输出，不含实现细节
    _load/_scan/_emit 等：具体实现层（每个函数只做一件事，抽象层次一致）

核心原则（v0.1 定案）：
    WenLint 只负责"发现"——定位 + 规则 ID + 命中文本 + 上下文 + review_hint。
    **不修改任何正文**（无 --fix/--apply）。判断/查证/改写由 Skill 的 LLM 完成。

用法：
    wenlint <path>                     review
    wenlint <path> --json              JSON 输出（含 sentence/before/after/review_hint）
    wenlint <path> --profile academic  场景 profile
    wenlint <path> --fail-level warning  存在 >= 该级别时 exit 1（CI）
"""
import argparse
import json
import os
import sys

from . import __version__
from .profiles import PROFILES
from .scanner import scan_text

LEVEL_RANK = {"error": 3, "warning": 2, "suggestion": 1, "candidate": 0}
DOC_EXTS = (".md", ".txt", ".rst", ".markdown")
# 目录扫描时跳过的非源码目录（文档模板类不在此列，由各项目 .wenlintignore 自决）
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "build", "dist",
             "__pycache__", ".pytest_cache", ".archive"}


# ============ 路由层 ============

def main(argv=None):
    """CLI 入口：极轻路由，只做参数解析与 review 分发。

    Args:
        argv: 命令行参数列表；None 时用 sys.argv[1:]。

    Returns:
        int：进程退出码（0 通过 / 1 有 ≥fail-level 命中 / 2 无输入文件）。
    """
    args = _parse_args(argv)
    files = _collect_files(args.path)
    if not files:
        print(f"!! 未找到可检查文件: {args.path}", file=sys.stderr)
        return 2
    return _run_review(files, args)


# ============ 参数与输入 ============

def _parse_args(argv):
    """解析命令行参数（argparse 细节，不承载业务逻辑）。

    Args:
        argv: 原始参数列表。

    Returns:
        argparse.Namespace：含 path/json/profile/fail-level/quiet 等。
    """
    p = argparse.ArgumentParser(
        prog="wenlint",
        description="WenLint：中文写作静态检查器（发现候选，不修改正文）",
    )
    p.add_argument("path", nargs="+", help="文件或目录（可多个）")
    p.add_argument("--version", action="version", version=f"wenlint {__version__}")
    p.add_argument("--json", action="store_true",
                   help="JSON 输出（含上下文句与审查提示，供 LLM/Skill 消费）")
    p.add_argument("--profile", choices=sorted(PROFILES), default="general",
                   help="场景 profile：academic/product/formal/general")
    p.add_argument("--fail-level", choices=["error", "warning", "suggestion"],
                   default=None, help="存在 >= 该级别的命中时 exit 1（默认不失败）")
    p.add_argument("--quiet", action="store_true", help="只输出汇总")
    return p.parse_args(argv)


def _effective_profile(fp, requested):
    """按文件类型决定生效 profile。

    规则：SKILL.md（指令文档）长句收紧到 50 字（instruction profile），
    其余文件用请求的 profile；用户显式指定 --profile 时一律尊重。

    Args:
        fp: 文件路径。
        requested: 用户请求的 profile 名。

    Returns:
        str：实际生效的 profile 名。
    """
    if requested != "general":
        return requested
    if fp.endswith("SKILL.md"):
        return "instruction"
    return requested


def _load_ignore(cwd):
    """读取 cwd/.wenlintignore（每行一个 glob 模式，# 开头为注释）。

    Args:
        cwd: 运行目录。

    Returns:
        list[str]：忽略模式列表（无文件则空）。
    """
    p = os.path.join(cwd, ".wenlintignore")
    try:
        with open(p, encoding="utf-8") as f:
            return [ln.strip() for ln in f
                    if ln.strip() and not ln.startswith("#")]
    except OSError:
        return []


def _collect_files(paths):
    """收集待检查文件（多路径输入展开）。

    跳过常见非源码目录与隐藏目录；每个输入目录若有 .wenlintignore，
    按**项目根相对路径**应用忽略（pattern 尾 / 表示目录前缀）。

    Args:
        paths: 文件或目录路径列表。

    Returns:
        list[str]：排序去重后的文件路径（.md/.txt/.rst/.markdown）。
    """
    files = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
            continue
        ignore = _load_ignore(p)   # 项目自己的 .wenlintignore（相对项目根）
        for root, dirs, fs in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                       and not d.startswith(".")]
            for f in fs:
                if not f.endswith(DOC_EXTS):
                    continue
                fp = os.path.join(root, f)
                if ignore and _ignored(fp, ignore, p):
                    continue
                files.append(fp)
    return sorted(set(files))


def _ignored(fp, patterns, base=None):
    """判断文件是否匹配任一忽略模式。

    目录语义：pattern 以 / 结尾（如 "tests/"）→ 相对路径前缀匹配；
    否则 fnmatch glob（相对路径或 basename）。

    Args:
        fp: 文件路径。
        patterns: .wenlintignore 模式列表。
        base: 项目根（模式相对的基准）；None 时用 cwd。

    Returns:
        bool：True 表示应忽略。
    """
    import fnmatch
    try:
        rel = os.path.relpath(fp, base or os.getcwd())
    except ValueError:
        # Cross-volume paths (Windows) cannot be relativized; keep absolute form.
        rel = fp
    for pat in patterns:
        if pat.endswith("/"):
            if rel.startswith(pat):
                return True
        elif fnmatch.fnmatch(rel, pat) \
                or fnmatch.fnmatch(os.path.basename(fp), pat):
            return True
    return False


def _load_texts(files):
    """批量读取文件内容。

    Args:
        files: 文件路径列表。

    Returns:
        dict[str, str]：{fp: text}；不可读/非 UTF-8 文件跳过并输出告警。
    """
    texts = {}
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as fh:
                texts[fp] = fh.read()
        except (OSError, UnicodeDecodeError) as e:
            print(f"!! 无法读取 {fp}: {e}", file=sys.stderr)
    return texts


def _display_path(fp):
    """文件路径的展示形式（绝对路径转相对路径；相对更长时用绝对）。

    Args:
        fp: 文件路径。

    Returns:
        str：展示用路径。
    """
    if not os.path.isabs(fp):
        return fp
    try:
        rel = os.path.relpath(fp)
    except ValueError:
        return fp
    return rel if len(rel) <= len(fp) else fp


# ============ review 入口（业务步骤编排）============

def _run_review(files, args):
    """Review 业务步骤编排：加载 → 扫描 → 输出 → 退出码。

    Args:
        files: 待检查文件列表。
        args: 解析后的命令行参数。

    Returns:
        int：退出码（--fail-level 生效时按最重命中判定）。
    """
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
    """批量扫描（按文件逐个执行 scan_text）。

    Args:
        texts: {fp: text} 映射。
        profile: 请求的 profile（内部再按文件类型细化）。

    Returns:
        list[tuple[str, list]]：[(fp, findings), ...]。
    """
    results = []
    for fp, text in texts.items():
        results.append((fp, scan_text(text, profile=_effective_profile(fp, profile),
                                      filename=fp)))
    return results


def _emit_json(results, texts):
    """输出 JSON（供 Skill/LLM 消费的结构化候选）。

    Args:
        results: [(fp, findings), ...]。
        texts: {fp: text}，用于提取命中行上下文。
    """
    out = []
    for fp, findings in results:
        lines = texts[fp].split("\n")
        for f in findings:
            ln = f["line"]
            out.append({
                "rule": f["rule_id"],
                "type": "candidate" if f["severity"] == "candidate" else "lint",
                "severity": f["severity"],
                "category": f["category"],
                "message": f["message"],
                "review_hint": f["review_hint"],
                "file": fp,
                "line": ln,
                "column": f["col"],
                "text": f["match"],
                "sentence": f["sentence"],
                "before": lines[ln - 2] if ln >= 2 else None,
                "after": lines[ln] if ln < len(lines) else None,
            })
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _emit_summary(results):
    """输出命中汇总（文件: 数量 + 总数）。

    Args:
        results: [(fp, findings), ...]。
    """
    per = "  ".join(f"{_display_path(fp)}: {len(h)}" for fp, h in results if h)
    total = sum(len(h) for _, h in results)
    print(f"\n✖ {total} 处（{per}）")


def _format_finding(fp, f):
    """单条命中的文本行（vale 风格：文件:行:列  ID  级别  类别  消息）。

    Args:
        fp: 文件路径。
        f: finding dict。

    Returns:
        str：格式化后的命中行。
    """
    msg = f["message"]
    if f["match"]:
        msg = f"{msg} 「{f['match']}」" if "「" not in msg else msg
    return (f"{_display_path(fp)}:{f['line']}:{f['col']}  "
            f"{f['rule_id']:<5} {f['severity']:<10} {f['category']}  {msg}")


def _exit_code(findings, fail_level):
    """按 fail_level 计算进程退出码。

    Args:
        findings: 全部命中列表（可为空）。
        fail_level: error/warning/suggestion 或 None（不失败）。

    Returns:
        int：0 或 1。
    """
    if not fail_level:
        return 0
    worst = max((LEVEL_RANK[f["severity"]] for f in findings), default=0)
    return 1 if worst >= LEVEL_RANK[fail_level] else 0


if __name__ == "__main__":
    sys.exit(main())
