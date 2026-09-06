"""扫描引擎：规则执行（词表/句/重复/文件级 A900）。

分层：rules.py 声明规则（数据），本模块按规则类型分发执行。
"""

import re

from .markdown import line_role, mask_text
from .profiles import PROFILES
from .rules import RULES, by_id

DEFAULT_PROFILE = "general"


def _compile(rule):
    """编译单条规则的 patterns 与 block 为正则对象。

    Args:
        rule: 规则 dict（含 patterns 列表与可选 block 字符串）。

    Returns:
        (patterns, block)：编译后的正则列表与排除正则（无则 None）。
        非法正则自动转义为字面匹配，保证规则错误不崩溃。
    """
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
    """计算文本的中文字符占比（语言守卫用）。

    Args:
        s: 任意字符串。

    Returns:
        float：中文字符数 / 总长度；空串返回 0.0。
    """
    if not s:
        return 0.0
    cn = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return cn / len(s)


def scan_text(text, profile=DEFAULT_PROFILE, filename="<text>"):  # noqa: PLR0912,PLR0914 规则分发核心，特判分支是本质复杂度
    """扫描文本，返回按行列排序的 findings 列表。

    Args:
        text: 待扫描的完整文本。
        profile: profile 名（general/academic/product/formal/instruction）。
        filename: 文件名，用于文件级规则（A900 按 SKILL.md 后缀触发）。

    Returns:
        list[dict]，每条含 line/col/rule_id/severity/category/match/message。

    Notes:
        - 语言守卫：中文字符占比 <5% 视为非中文文件，直接返回空。
        - semantic 规则（C002/H002/H003）命中降级为 candidate，不阻断 CI。
        - S001 仅对散文段落行判句长（vale scope 借鉴），剥 markdown 标记。
    """
    if _cn_ratio(text) < 0.05:
        return []

    # A900 文件级规则：SKILL.md 主文件过大（God File 坏味）
    if filename.endswith("SKILL.md"):
        rule = by_id("A900")
        n_lines = text.count("\n") + 1
        if rule and n_lines > rule.get("max_lines", 300):
            findings_900 = [{
                "line": 1, "col": 1, "rule_id": "A900",
                "severity": rule["severity"], "category": rule["category"],
                "match": "", "message": rule["message"].format(
                    len=n_lines, max=rule.get("max_lines", 300)),
            }]
        else:
            findings_900 = []
    else:
        findings_900 = []

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
        needs_semantic = rule.get("semantic", False)
        severity = sev_ov.get(rid, rule["severity"])
        if needs_semantic:
            severity = "candidate"   # 语义候选：不阻断 CI，交 LLM/人工裁决
        rpats, rblock = _COMPILED[rid]

        if rid == "S001":   # 超长句：scope=paragraph（vale 借鉴）——只判散文段落行，
            # 列表项/导航/标题/表格是结构不是句子；同时剥掉 ** 等标记符号再计数
            max_len = params.get("S001", {}).get("max_len", rule.get("max_len", 80))
            for ln, (mline, raw) in enumerate(zip(masked, raw_lines), 1):
                if line_role(raw) != "paragraph":
                    continue
                # 剥粗体/强调标记（**、__、*、_）后计数——标记不是句子内容
                clean = re.sub(r"\*\*|__|\*|_|`", "", mline.strip())
                for seg in re.split(r"(?<=[。！？!?；;])", clean):
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

    findings += findings_900
    findings.sort(key=lambda f: (f["line"], f["col"]))
    return findings
