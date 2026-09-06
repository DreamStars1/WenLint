"""WenLint 检测引擎 v0.1。

核心设计（修复 0.1.x 评审 P0）：
1. 等长 mask：代码块/行内代码/URL/图片/注释/front matter 替换为**等长空格**
   → 行号列号与原文一一对应，不会偏移
2. review 与 fix 共用 mask；fix 额外保护引号内内容（示例词/引用不被误删）
3. scan 与 fix 都基于文本函数（scan_text），--fix 剩余 = 扫描修复后文本
"""
import re

from .rules import RULES, by_id
from .profiles import PROFILES

DEFAULT_PROFILE = "general"

# ---------- 保护区间 ----------
_FENCE_RE = re.compile(r"^(```|~~~)")


def _blank(s):
    return " " * len(s)


def mask_line(line, protect_quotes=False):
    """把一行内的受保护内容替换为等长空格。返回 (masked, protected_count)。
    protect_quotes=True 时额外保护引号内内容（fix 模式用）。"""
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
    masked = re.sub(r"<!--.*?-->", lambda m: _blank(m.group(0)), masked, flags=re.S)
    # 删除线
    masked = re.sub(r"~~[^~\n]*~~", lambda m: _blank(m.group(0)), masked)
    if protect_quotes:
        # 引号内内容（中文引号/英文引号），防 fix 误删示例词/引用
        masked = re.sub(r"[“”\"'][^“”\"'\n]*[“”\"']",
                        lambda m: _blank(m.group(0)), masked)
    return masked


def mask_text(text, protect_quotes=False):
    """整段 mask：front matter 保留行数，代码块整块屏蔽。
    返回 masked 文本（与原文等长、等行数）。"""
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
def _compile(rule):
    pats = []
    for p in rule.get("patterns", []):
        try:
            pats.append(re.compile(p))
        except re.error:
            pats.append(re.compile(re.escape(p)))
    block = None
    if rule.get("block"):
        block = re.compile(rule["block"])
    return pats, block


_COMPILED = {r["id"]: _compile(r) for r in RULES}


def _cn_ratio(s):
    """中文字符占比"""
    if not s:
        return 0.0
    cn = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return cn / len(s)


def scan_text(text, profile=DEFAULT_PROFILE, filename="<text>"):
    """扫描文本，返回 findings 列表（按行、列排序）。
    finding: dict(line, col, rule_id, severity, category, match, message)
    语言守卫：wenlint 是中文 linter——文本中文字符占比 <5% 视为非中文文件，跳过。
    """
    if _cn_ratio(text) < 0.05:
        return []
    prof = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
    disabled = set(prof.get("disable", []))
    sev_ov = prof.get("severity_override", {})
    params = prof.get("params", {})

    findings = []
    masked = mask_text(text, protect_quotes=True).split("\n")
    raw_lines = text.split("\n")

    for rule in RULES:
        rid = rule["id"]
        if rid in disabled:
            continue
        severity = sev_ov.get(rid, rule["severity"])
        rpats, rblock = _COMPILED[rid]

        if rid == "S001":   # 超长句：逐行按句读拆，跳过表格行/低中文占比行
            max_len = params.get("S001", {}).get("max_len", rule.get("max_len", 60))
            for ln, mline in enumerate(masked, 1):
                stripped = mline.strip()
                if not stripped or stripped.startswith("|") or stripped.startswith("#"):
                    continue
                for seg in re.split(r"(?<=[。！？!?；;])", stripped):
                    seg = seg.strip()
                    # 语言守卫：中文字符占比 <30% 的行（英文/代码/URL 行）不判长句
                    if len(seg) > max_len and _cn_ratio(seg) >= 0.30:
                        findings.append({
                            "line": ln, "col": 1, "rule_id": rid,
                            "severity": severity, "category": rule["category"],
                            "match": "", "message": rule["message"].format(
                                len=len(seg), max=max_len),
                        })
            continue

        if rid == "D001":   # 相邻重复（jieba 词级，简化：中文 2-8 字连续重复）
            dup_re = re.compile(r"([\u4e00-\u9fff]{2,8})\1")
            for ln, mline in enumerate(masked, 1):
                for m in dup_re.finditer(mline):
                    findings.append({
                        "line": ln, "col": m.start() + 1, "rule_id": rid,
                        "severity": severity, "category": rule["category"],
                        "match": m.group(1) * 2,
                        "message": rule["message"].format(w=m.group(1)),
                    })
            continue

        # 通用词/正则规则
        for ln, (mline, raw) in enumerate(zip(masked, raw_lines), 1):
            for pat in rpats:
                for m in pat.finditer(mline):
                    if m.start() >= len(mline):
                        continue
                    matched = m.group(0)
                    if not matched.strip():
                        continue
                    if rblock and rblock.search(raw[max(0, m.start() - 10): m.end() + 10]):
                        continue
                    w = matched
                    findings.append({
                        "line": ln, "col": m.start() + 1, "rule_id": rid,
                        "severity": severity, "category": rule["category"],
                        "match": w,
                        "message": rule["message"].format(w=w, len=0, max=0),
                    })

    findings.sort(key=lambda f: (f["line"], f["col"]))
    return findings


def scan_file(path, profile=DEFAULT_PROFILE):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return scan_text(text, profile=profile, filename=path)


# ---------- 修复 ----------
class FixableWord:
    def __init__(self, rid, word):
        self.rid, self.word = rid, word


def fix_text(text, profile=DEFAULT_PROFILE):
    """安全自动修复：仅处理 fixable=True 的高置信规则。
    绝不触碰：代码块、行内代码、URL、引号内内容、front matter。
    候选位置在等长 masked 行上取得 → 天然跳过受保护内容；
    从后往前删除 → 前面候选位置不受影响。
    返回 (fixed_text, changes[(行号, 规则ID, 说明)])。
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
