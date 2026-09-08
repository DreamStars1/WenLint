"""扫描引擎：规则执行（词表/句/重复/文件级 A900）。

分层：rules.py 声明规则（数据），本模块按规则类型分发执行。
"""

import re

from .markdown import (
    classify_lines,
    is_table_delimiter_row,
    iter_table_cells,
    mask_text,
    parse_atx_heading,
    parse_heading_number,
)
from .profiles import PROFILES
from .rules import RULES, by_id

# scan_text 是规则分发核心，分支/局部变量是本质复杂度
# pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks
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


def scan_text(text, profile=DEFAULT_PROFILE, filename="<text>"):
    """扫描文本，返回按行列排序的 findings 列表。

    Args:
        text: 待扫描的完整文本。
        profile: profile 名（general/academic/product/formal/instruction）。
        filename: 文件名，用于文件级规则（A900 按 SKILL.md 后缀触发）。

    Returns:
        list[dict]，每条含 line/col/rule_id/severity/category/match/message。

    Notes:
        - 无文件级语言守卫：英文文件的中文片段照常检查（行级 S001 守卫已够）。
        - semantic 规则（C002/H002/H003）命中降级为 candidate，不阻断 CI。
        - S001 聚合连续散文段落判句长；词规则在正文行与表格单元格执行
          （heading/fence 仍跳过词法；标题另走结构规则）。
    """
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
    masked = mask_text(text).split("\n")
    raw_lines = text.split("\n")
    roles = classify_lines(raw_lines)

    # 正文行角色：词规则只在这些行执行（heading/fence 是结构非散文）
    PROSE_ROLES = ("paragraph", "list_item", "blockquote")
    STRUCTURE_RULES = {"DOC001", "DOC002"}

    findings.extend(_scan_heading_structure(raw_lines, masked, disabled, sev_ov))

    for rule in RULES:
        rid = rule["id"]
        if rid in disabled or rid in STRUCTURE_RULES:
            continue
        needs_semantic = rule.get("semantic", False)
        severity = sev_ov.get(rid, rule["severity"])
        if needs_semantic:
            severity = "candidate"   # 语义候选：不阻断 CI，交 LLM/人工裁决
        rpats, rblock = _COMPILED[rid]

        if rid == "S001":   # 超长句：聚合连续散文段落后按句读判长
            # （vale scope 借鉴；剥 ** 等标记；跨行精确定位，不吞同段多命中）
            max_len = params.get("S001", {}).get("max_len", rule.get("max_len", 80))
            for _, para, raw_para, bounds in _collect_paragraphs(
                    masked, raw_lines, roles):
                cursor = 0
                for seg in re.split(r"(?<=[。！？!?；;])", para):
                    seg_stripped = seg.strip()
                    # 剥 Markdown 标记；空白（含 mask 占位与软换行）不计句长
                    clean = re.sub(r"\*\*|__|\*|_|`", "", seg_stripped)
                    measurable = re.sub(r"\s+", "", clean)
                    if len(measurable) > max_len and _cn_ratio(measurable) >= 0.30:
                        # Exact span in the original aggregated paragraph text.
                        raw_start = cursor
                        raw_end = cursor + len(seg)
                        while raw_start < raw_end and raw_para[raw_start].isspace():
                            raw_start += 1
                        while raw_end > raw_start and raw_para[raw_end - 1].isspace():
                            raw_end -= 1
                        exact = raw_para[raw_start:raw_end]
                        ln, col = _locate(bounds, raw_start)
                        findings.append({
                            "line": ln, "col": col, "rule_id": rid,
                            "severity": severity, "category": rule["category"],
                            "match": exact, "message": rule["message"].format(
                                len=len(measurable), max=max_len),
                            "sentence": exact,
                        })
                    cursor += len(seg)
            findings.extend(
                _scan_table_cells_s001(
                    raw_lines, masked, roles, rule, severity, max_len)
            )
            continue

        if rid == "D001":   # 相邻重复（中文 2-8 字连续重复）
            dup_re = re.compile(r"([\u4e00-\u9fff]{2,8})\1")
            for ln, (mline, raw) in enumerate(zip(masked, raw_lines), 1):
                if roles[ln - 1] not in PROSE_ROLES:
                    continue
                for m in dup_re.finditer(mline):
                    findings.append({
                        "line": ln, "col": m.start() + 1, "rule_id": rid,
                        "severity": severity, "category": rule["category"],
                        "match": m.group(1) * 2,
                        "message": rule["message"].format(w=m.group(1)),
                    })
            findings.extend(
                _scan_table_cells_d001(
                    raw_lines, masked, roles, rule, severity, dup_re)
            )
            continue

        # 通用词/正则规则（正文行 + 表格单元格）
        for ln, (mline, raw) in enumerate(zip(masked, raw_lines), 1):
            if roles[ln - 1] not in PROSE_ROLES:
                continue
            for pat in rpats:
                for m in pat.finditer(mline):
                    if m.start() >= len(mline):
                        continue
                    matched = m.group(0)
                    if not matched.strip():
                        continue
                    if rblock and rblock.match(raw, m.start()):
                        # block 锚定当前命中起点（词后例外模式），
                        # 不能搜索附近任意位置（会误豁免邻接的真命中）
                        continue
                    findings.append({
                        "line": ln, "col": m.start() + 1, "rule_id": rid,
                        "severity": severity, "category": rule["category"],
                        "match": matched,
                        "message": rule["message"].format(w=matched, len=0, max=0),
                    })
        findings.extend(
            _scan_table_cells_patterns(
                raw_lines, masked, roles, rule, severity, rpats, rblock)
        )

    findings += findings_900

    # span 级去重（同 line+col+rule 完全相同才去）：
    # 不合并同规则多次命中（"大概…好像…"各自保留，语义层逐条处理）
    seen, merged = set(), []
    for f in findings:
        key = (f["line"], f["col"], f["rule_id"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(f)
    findings = merged

    # 补充规则审查提示（review_hint）与命中句（sentence，供 Skill 消费）
    # S001 已写入跨行完整句，此处不覆盖。
    for f in findings:
        rule = by_id(f["rule_id"])
        f["review_hint"] = rule.get("review_hint", "") if rule else ""
        if f.get("sentence"):
            continue
        ln = f["line"]
        if 1 <= ln <= len(raw_lines):
            f["sentence"] = _extract_sentence(raw_lines[ln - 1], f["col"])
        else:
            f["sentence"] = ""

    findings.sort(key=lambda f: (f["line"], f["col"]))
    return findings


def _collect_paragraphs(masked_lines, raw_lines, roles):
    """聚合连续散文段落行为段落，附带字符偏移 → 原文位置的行界映射。

    Markdown 中一个段落可被手动换行拆成多行；若逐行判句长，
    拆行后每段都 < 阈值就会漏报。这里把连续 paragraph 行用换行拼接后统一切句，
    并保留行首空白以便列号映射回原文；同时保留等长原文拼接供 sentence 上下文。

    Args:
        masked_lines: mask 后各行。
        raw_lines: 原文各行（用于 sentence 原文）。
        roles: Per-line roles from :func:`classify_lines`.

    Returns:
        list[tuple[int, str, str, list]]：
        [(段落起始行号, masked 拼接, 原文拼接, 行界)]。
        行界 = [(累计字符数, 行号), ...]，每行拼接后追加一条；
        给定字符偏移 pos，落在 [prev_cum, cum) 的即为该行，
        行内列号 = pos - prev_cum + 1。
    """
    paras = []
    start_ln, buf, raw_buf, bounds = 0, "", "", []
    for ln, (mline, raw) in enumerate(zip(masked_lines, raw_lines), 1):
        # A prose line containing only protected Markdown (for example inline
        # code) is still part of its surrounding paragraph.  Use the raw line
        # to distinguish it from an actual blank line, while the masked text
        # continues to contribute zero measurable characters.
        if roles[ln - 1] == "paragraph" and raw.strip():
            if not buf:
                start_ln = ln
                buf, raw_buf = mline, raw
            else:
                buf += "\n" + mline
                raw_buf += "\n" + raw
            bounds.append((len(buf), ln))
        else:
            if buf:
                paras.append((start_ln, buf, raw_buf, bounds))
            start_ln, buf, raw_buf, bounds = 0, "", "", []
    if buf:
        paras.append((start_ln, buf, raw_buf, bounds))
    return paras


def _locate(bounds, pos):
    """把段落内字符偏移映射回 (line, col)。

    Args:
        bounds: _collect_paragraphs 返回的行界。
        pos: 段内字符偏移（0-based）。

    Returns:
        (line, col)：1-based 行号与列号。
    """
    prev_cum, prev_ln = 0, bounds[0][1]
    for cum, ln in bounds:
        if pos < cum:
            return ln, pos - prev_cum + 1
        # Paragraph lines are joined with one synthetic newline.  It belongs
        # to neither source line, so the next line starts one character after
        # the previous cumulative boundary.
        prev_cum, prev_ln = cum + 1, ln
    return prev_ln, pos - prev_cum + 1


def _extract_sentence(line, col):
    """从命中行提取包含该位置的句子片段（按句读切分）。

    Args:
        line: 命中所在行原文。
        col: 命中列（1-based）。

    Returns:
        str：包含命中位置的句段；无句读时返回整行。列号越界时返回整行。
    """
    if not line:
        return ""
    idx = max(0, col - 1)
    if idx >= len(line):
        return line
    segs = re.split(r"(?<=[。！？!?；;])", line)
    pos = 0
    for seg in segs:
        if pos <= idx < pos + len(seg):
            return seg.strip()
        pos += len(seg)
    return line


def _scan_heading_structure(raw_lines, masked_lines, disabled, sev_ov):
    """Emit DOC001/DOC002 findings for ATX / projected headings.

    Candidates are recognized on raw lines, but globally excluded regions
    (fence bodies, front matter, multi-line HTML comments, indented code)
    are skipped when the corresponding document-level masked line is fully
    blank. Title emptiness and numbering still come from the raw heading so
    inline-code titles are not mistaken for DOC001.

    Args:
        raw_lines: Original document lines.
        masked_lines: Equal-length ``mask_text`` lines aligned to ``raw_lines``.
        disabled: Rule ids disabled by the active profile.
        sev_ov: Severity overrides from the profile.

    Returns:
        list[dict]: Structure findings (may use empty ``match``).
    """
    findings = []
    doc001 = by_id("DOC001")
    doc002 = by_id("DOC002")
    # Stack of (level, occurrence_id) for open ancestors. occurrence_id is the
    # 1-based source line so nonnumeric parents stay distinct across siblings.
    stack = []
    last_sibling = {}

    for ln, (raw, masked) in enumerate(zip(raw_lines, masked_lines), 1):
        parsed = parse_atx_heading(raw)
        if parsed is None:
            continue
        # Excluded interiors are equal-length spaces; keep raw parse for title.
        if _line_fully_masked(masked):
            continue
        level, title = parsed
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_key = tuple(stack)
        if doc001 and "DOC001" not in disabled and not title:
            sev = sev_ov.get("DOC001", doc001["severity"])
            findings.append({
                "line": ln,
                "col": 1,
                "rule_id": "DOC001",
                "severity": sev,
                "category": doc001["category"],
                "match": "",
                "message": doc001["message"],
                "sentence": raw.strip(),
            })
        number = parse_heading_number(title) if title else None
        if (
            doc002
            and "DOC002" not in disabled
            and number is not None
        ):
            parts, label = number
            key = (parent_key, level)
            prev = last_sibling.get(key)
            if prev is not None:
                prev_parts, prev_label = prev
                if (
                    len(prev_parts) == len(parts)
                    and prev_parts[:-1] == parts[:-1]
                    and parts[-1] - prev_parts[-1] > 1
                ):
                    sev = sev_ov.get("DOC002", doc002["severity"])
                    # Point at the later heading title start when possible.
                    col = raw.find(title) + 1 if title in raw else 1
                    findings.append({
                        "line": ln,
                        "col": col,
                        "rule_id": "DOC002",
                        "severity": sev,
                        "category": doc002["category"],
                        "match": "",
                        "message": doc002["message"].format(
                            prev=prev_label, curr=label),
                        "sentence": raw.strip(),
                    })
            last_sibling[key] = (parts, label)
        elif title and number is None:
            # Non-numeric titles break sibling numbering continuity so mixed
            # schemes stay unreported. Empty headings stay out of the chain.
            last_sibling.pop((parent_key, level), None)
        stack.append((level, ln))
    return findings


def _line_fully_masked(masked_line):
    """Return whether a document-level mask blanked the entire source line.

    Fence bodies, front matter, indented code, and multi-line HTML comment
    interiors become equal-length spaces; those regions must not receive
    table-cell scanning or heading-structure findings.
    """
    return not masked_line.strip()


def _iter_table_cells_for_scan(raw_line, masked_line):
    """Yield ``(col, raw_cell, masked_cell)`` aligned to the document mask.

    Cell boundaries still come from the raw GFM row (so escaped pipes and
    inline code keep their owning cell). Scan text comes from the equal-length
    document-level masked line at those exact offsets, so partial HTML comments
    and other global exclusions stay excluded.
    """
    for col, cell in iter_table_cells(raw_line):
        start = col - 1
        end = start + len(cell)
        yield col, cell, masked_line[start:end]


def _scan_table_cells_patterns(raw_lines, masked_lines, roles, rule, severity, rpats, rblock):
    """Run pattern rules independently inside each GFM table cell."""
    findings = []
    rid = rule["id"]
    for ln, (raw, masked) in enumerate(zip(raw_lines, masked_lines), 1):
        if roles[ln - 1] != "table" or is_table_delimiter_row(raw):
            continue
        if _line_fully_masked(masked):
            continue
        for col, cell, masked_cell in _iter_table_cells_for_scan(raw, masked):
            for pat in rpats:
                for m in pat.finditer(masked_cell):
                    matched = cell[m.start():m.end()]
                    if not matched.strip():
                        continue
                    abs_col = col + m.start()
                    if rblock and rblock.match(raw, abs_col - 1):
                        continue
                    findings.append({
                        "line": ln,
                        "col": abs_col,
                        "rule_id": rid,
                        "severity": severity,
                        "category": rule["category"],
                        "match": matched,
                        "message": rule["message"].format(
                            w=matched, len=0, max=0),
                    })
    return findings


def _scan_table_cells_d001(raw_lines, masked_lines, roles, rule, severity, dup_re):
    """Run adjacent-duplicate detection per table cell."""
    findings = []
    for ln, (raw, masked) in enumerate(zip(raw_lines, masked_lines), 1):
        if roles[ln - 1] != "table" or is_table_delimiter_row(raw):
            continue
        if _line_fully_masked(masked):
            continue
        for col, cell, masked_cell in _iter_table_cells_for_scan(raw, masked):
            for m in dup_re.finditer(masked_cell):
                word = cell[m.start():m.start() + len(m.group(1))]
                findings.append({
                    "line": ln,
                    "col": col + m.start(),
                    "rule_id": "D001",
                    "severity": severity,
                    "category": rule["category"],
                    "match": word * 2,
                    "message": rule["message"].format(w=word),
                })
    return findings


def _scan_table_cells_s001(raw_lines, masked_lines, roles, rule, severity, max_len):
    """Score long sentences per table cell without joining cells."""
    findings = []
    for ln, (raw, masked) in enumerate(zip(raw_lines, masked_lines), 1):
        if roles[ln - 1] != "table" or is_table_delimiter_row(raw):
            continue
        if _line_fully_masked(masked):
            continue
        for col, cell, masked_cell in _iter_table_cells_for_scan(raw, masked):
            cursor = 0
            for seg in re.split(r"(?<=[。！？!?；;])", masked_cell):
                seg_stripped = seg.strip()
                clean = re.sub(r"\*\*|__|\*|_|`", "", seg_stripped)
                measurable = re.sub(r"\s+", "", clean)
                if len(measurable) > max_len and _cn_ratio(measurable) >= 0.30:
                    raw_start = cursor
                    raw_end = cursor + len(seg)
                    while raw_start < raw_end and cell[raw_start:raw_start + 1].isspace():
                        raw_start += 1
                    while raw_end > raw_start and cell[raw_end - 1:raw_end].isspace():
                        raw_end -= 1
                    exact = cell[raw_start:raw_end]
                    findings.append({
                        "line": ln,
                        "col": col + raw_start,
                        "rule_id": "S001",
                        "severity": severity,
                        "category": rule["category"],
                        "match": exact,
                        "message": rule["message"].format(
                            len=len(measurable), max=max_len),
                        "sentence": exact,
                    })
                cursor += len(seg)
    return findings
