"""Markdown 保护层：行角色分类 + 等长 mask（保行号列号）。

设计要点：mask 用等长空格替换受保护内容，保证行号列号与原文一一对应，
是 scanner/fixer 共用的唯一文本保护来源（vale 需转 HTML 会丢行号，我们不用）。
"""

import re

# line_role 守卫式分类多 return 是合理风格
# pylint: disable=too-many-return-statements
# ---------- 保护区间 ----------
_FENCE_RE = re.compile(r"^(```|~~~)")


def line_role(line):
    """对一行做角色分类（vale scope 机制的轻量版）。

    Args:
        line: 原始行文本（未 strip）。

    Returns:
        str：paragraph（散文段落）/ heading / list_item / blockquote /
        table / fence（代码块）/ blank。S001 等规则按角色过滤。
    """
    s = line.strip()
    if not s:
        return "blank"
    if s.startswith(("```", "~~~")):
        return "fence"
    if s.startswith("#"):
        return "heading"
    if s.startswith(">"):
        return "blockquote"
    if s.startswith("|"):
        return "table"
    if re.match(r"^[-*+]\s", s) or re.match(r"^\d+[.、)]\s", s):
        return "list_item"
    # 缩进 4 空格（代码块）
    if line.startswith(("    ", "\t")):
        return "fence"
    return "paragraph"


def _blank(s):
    return " " * len(s)


def mask_line(line, protect_quotes=False):
    """把一行内的受保护内容替换为等长空格（长度不变，列号不漂移）。

    Args:
        line: 单行文本。
        protect_quotes: True 时额外保护引号内内容（fix 模式防误删示例词）。

    Returns:
        str：等长 masked 行，行内代码/图片 URL/链接 URL/HTML/注释/删除线
        被空格替代；链接文字保留（仍参与检查）。
    """
    masked = line
    # 行内代码
    masked = re.sub(r"`[^`\n]*`", lambda m: _blank(m.group(0)), masked)
    # 图片
    masked = re.sub(r"!\[[^\]]*\]\([^)]*\)", lambda m: _blank(m.group(0)), masked)
    # 链接 URL（保留文字部分，整体等长）
    def link_sub(m):
        keep = m.group(1)
        return keep + " " * (len(m.group(0)) - len(keep))
    masked = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", link_sub, masked)
    # HTML 标签 + 注释
    masked = re.sub(r"<[^>\n]+>", lambda m: _blank(m.group(0)), masked)
    masked = re.sub(r"<!--.*?-->", lambda m: _blank(m.group(0)), masked, flags=re.DOTALL)
    # 删除线
    masked = re.sub(r"~~[^~\n]*~~", lambda m: _blank(m.group(0)), masked)
    if protect_quotes:
        # 引号内内容（中文引号/英文引号），防 fix 误删示例词/引用
        masked = re.sub(r"[“”\"'][^“”\"'\n]*[“”\"']",
                        lambda m: _blank(m.group(0)), masked)
    return masked


def mask_text(text, protect_quotes=False):
    """整段 mask：front matter 保留行数、代码块整块屏蔽。

    Args:
        text: 完整文本（可含 front matter 与多行代码块）。
        protect_quotes: 传给 mask_line 的引号保护开关。

    Returns:
        str：与原文等长、等行数的 masked 文本（行号列号不变）。
    """
    lines = text.split("\n")
    out = []
    # front matter：--- 开头块，内容整块 blank（保留行）
    fm_end = -1
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break
    in_fence = False
    for i, line in enumerate(lines):
        if fm_end >= 0 and i <= fm_end:
            out.append(_blank(line) if line.strip() else line)
            continue
        stripped = line.lstrip()
        if _FENCE_RE.match(stripped):
            in_fence = not in_fence
            out.append(_blank(line))   # fence 标记本身也屏蔽（避免 ``` 内容误判）
            continue
        if in_fence:
            out.append(_blank(line))
            continue
        out.append(mask_line(line, protect_quotes))
    return "\n".join(out)


# ---------- 扫描 ----------
