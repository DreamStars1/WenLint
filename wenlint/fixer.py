"""安全修复：高置信白名单自动改（Markdown-safe）。"""
from .markdown import mask_text
from .profiles import PROFILES
from .scanner import _COMPILED

DEFAULT_PROFILE = "general"


def fix_text(text, profile=DEFAULT_PROFILE):  # noqa: PLR0914 多候选状态变量是修复逻辑所需
    """安全自动修复：仅处理高置信白名单规则（C001/C003/R002）。

    安全保证：代码块、行内代码、URL、引号内内容、front matter 全部不触碰——
    候选位置在等长 masked 行上取得（天然跳过受保护内容）；
    同一行多处命中时从后往前删除（前面候选位置不受影响）；
    词后接"的/之/地"等定语结构自动跳过。

    Args:
        text: 待修复文本。
        profile: profile 名（语义同 scan_text）。

    Returns:
        (fixed_text, changes)：修复后文本，与变更列表
        [(行号, 规则ID, 说明), ...]。
    """
    prof = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
    disabled = set(prof.get("disable", []))
    fixable_ids = [rid for rid in ("C001", "C003", "R002") if rid not in disabled]
    lines = text.split("\n")
    masked_all = mask_text(text, protect_quotes=True).split("\n")
    out, changes = [], []
    for i, (line, mline) in enumerate(zip(lines, masked_all), 1):
        if not mline.strip():
            out.append(line)      # front matter / 代码块内 / 空行：不碰
            continue
        # 收集候选（masked 行与原文等长）
        cands = []
        for rid in fixable_ids:
            for pat in _COMPILED[rid][0]:
                for m in pat.finditer(mline):
                    if m.group(0).strip():
                        cands.append((m.start(), rid, m.group(0)))
        if not cands:
            out.append(line)
            continue
        cands.sort(reverse=True)   # 从后往前删
        new = line
        for start, rid, w in cands:
            if start >= len(new):
                continue
            tail = new[start + len(w):].lstrip()
            if tail.startswith(("的", "之", "地", "和", "与", "同", "及")):
                continue          # 定语结构保护（如"综上所述的方案"）
            if tail.startswith(("，", ",", "、", "；", ";")):
                tail = tail[1:].lstrip()
            fixed = new[:start] + tail
            if fixed != new:
                changes.append((i, rid, f"删除套话「{w}」"))
                new = fixed
        out.append(new)
    return "\n".join(out), changes
