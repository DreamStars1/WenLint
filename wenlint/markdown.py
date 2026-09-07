"""Markdown 保护层：行角色分类 + 等长 mask（保行号列号）。

设计要点：
- mask 用等长空格替换"非正文内容"（代码块/行内代码/URL/HTML 标签/注释），
  保证行号列号与原文一一对应（vale 转 HTML 会丢行号，我们不用）。
- 只保护确定非正文的内容；括号/引号内的正文**照常检查**——
  示例词等元语境由语义层（LLM）判断 KEEP，不由规则层静默放过。
- 链接只保护 [ ](url) 部分，链接文字保留在原列号继续检查。
"""

import re

# pylint: disable=too-many-return-statements,too-many-branches,too-many-statements
# line_role 守卫式分类，多 return 是合理风格


def line_role(line):
    """对一行做角色分类（vale scope 机制的轻量版）。

    Args:
        line: 原始行文本（未 strip）。

    Returns:
        str：paragraph（散文段落）/ heading / list_item / blockquote /
        table / fence（代码块）/ blank。规则按角色决定是否执行。
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
    if line.startswith(("    ", "\t")):
        return "fence"
    return "paragraph"


def _blank(s):
    """返回与 s 等长的空格串（保列号）。"""
    return " " * len(s)


def _link_mask(m):
    """链接 mask：blank 掉 [ 与 ](url)，链接文字保留在原列号。

    Args:
        m: 完整链接 match（[text](url)）。

    Returns:
        str：等长字符串——"[" 换 1 空格，文字原样保留，"]" + "(url)" 换空格。
        这样文字在 masked 行中的列号与原文一致，命中列号不偏移。
    """
    return _blank("[") + m.group(1) + _blank("]" + "(" + m.group(2) + ")")


def mask_line(line):
    """把一行内的受保护内容替换为等长空格（长度不变，列号不漂移）。

    Args:
        line: 单行文本。

    Returns:
        str：等长 masked 行。行内代码/图片/HTML 标签/删除线被空格替代；
        链接 URL 被替代但链接文字保留在原位。
    """
    masked = line
    # 行内代码
    masked = re.sub(r"`[^`\n]*`", lambda m: _blank(m.group(0)), masked)
    # 图片（alt 与 URL 都是非正文）
    masked = re.sub(r"!\[[^\]]*\]\([^)]*\)", lambda m: _blank(m.group(0)), masked)
    # 链接：文字保留原列号，[ ](url) 屏蔽
    masked = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", _link_mask, masked)
    # HTML 标签
    masked = re.sub(r"<[^>\n]+>", lambda m: _blank(m.group(0)), masked)
    # 删除线
    masked = re.sub(r"~~[^~\n]*~~", lambda m: _blank(m.group(0)), masked)
    return masked


def _strip_inline_code(line):
    """行内代码占位（供 HTML 注释识别前使用：代码内的 <!-- 不应触发注释状态）。

    Args:
        line: 单行文本。

    Returns:
        str：与 line 等长，行内代码段已换空格。
    """
    return re.sub(r"`[^`\n]*`", lambda m: _blank(m.group(0)), line)


def _fence_marker(line):
    """解析围栏标记：返回 (字符, 长度, 后缀)，非围栏则 None。

    CommonMark：关闭围栏须同字符，且长度 ≥ 开围栏；较短围栏不能提前关闭较长围栏。
    """
    match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
    if not match:
        return None
    run = match.group(1)
    return run[0], len(run), match.group(2)


def mask_text(text):
    """整段 mask：front matter/代码块/缩进代码/多行注释 整块屏蔽。

    状态机逐行处理，顺序（代码区优先于注释识别，防代码内 <!-- 破坏状态）：
    front matter → 围栏内 → 围栏开关 → 缩进代码 → 行内代码占位 →
    HTML 注释 → 行内 mask。除被屏蔽区域外的普通行再过 mask_line。
    返回与原文等长、等行数的文本（行号列号不变）。

    Args:
        text: 完整文本。

    Returns:
        str：等长 masked 文本。
    """
    lines = text.split("\n")
    out = []
    in_fence = False        # ``` 围栏内
    fence_char = None       # 开围栏字符（` 或 ~）
    fence_len = 0           # 开围栏长度；关闭须 ≥ 此长度且同字符
    in_indent = False       # 缩进代码块内
    in_comment = False      # 多行 HTML 注释内
    in_front = 0            # front matter 深度（0/1/2）

    for i, line in enumerate(lines):
        s = line.strip()

        # 围栏内：整行屏蔽（代码内容不参与任何注释/正文识别）
        if in_fence:
            marker = _fence_marker(line)
            if (marker and marker[0] == fence_char and marker[1] >= fence_len
                    and not marker[2].strip()):
                out.append(line)
                in_fence = False
                fence_char, fence_len = None, 0
            else:
                out.append(_blank(line))
            continue
        # 围栏开关
        marker = _fence_marker(line)
        if marker:
            out.append(line)
            in_fence = True
            fence_char, fence_len = marker[:2]
            continue

        # 缩进代码块：文件开头或空行后出现 4 空格/制表符缩进
        is_indented = line.startswith(("    ", "\t"))
        if is_indented:
            prev_blank = i == 0 or not lines[i - 1].strip()
            if in_indent or prev_blank:
                out.append(_blank(line))
                in_indent = True
                continue
        else:
            in_indent = False

        # front matter：开头 --- 起，第二个 --- 止，其间内容屏蔽
        if i == 0 and s == "---":
            in_front = 1
            out.append(line)
            continue
        if in_front == 1:
            if s == "---":
                in_front = 2
                out.append(line)
            else:
                out.append(_blank(line))
            continue

        # 行内代码占位后再识别 HTML 注释：`<!--` 在代码里不触发注释状态
        check = _strip_inline_code(line)

        if in_comment:
            if "-->" in check:
                end = check.find("-->") + 3
                out.append(_blank(check[:end]) + mask_line(line[end:]))
                in_comment = False
            else:
                out.append(_blank(line))
            continue
        if "<!--" in check:
            s_begin = check.find("<!--")
            if "-->" in check:
                e_end = check.find("-->") + 3
                # 单行注释：注释前正文 mask + 注释段 blank + 注释后正文 mask
                out.append(mask_line(line[:s_begin]) +
                           _blank(line[s_begin:e_end]) +
                           mask_line(line[e_end:]))
            else:
                # 多行注释开始行：<!-- 前正文 mask，注释段 blank 到行尾
                out.append(mask_line(line[:s_begin]) + _blank(line[s_begin:]))
                in_comment = True
            continue

        # 普通行：行内 mask（引号与括号内容不保护，照常检查）
        out.append(mask_line(line))

    return "\n".join(out)
