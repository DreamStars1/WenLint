#!/usr/bin/env python3
"""zh-prose-smell: 中文散文坏味检查器（jieba 分词 + 词表规则）
用法: python zh_prose_smell.py <file.md|dir> [--json]

检测类别:
  AI味/废话填充   总而言之、值得注意的是、众所周知...
  模糊词          大概、可能、好像、似乎...
  空洞强调        非常、十分、极其、真的...
  冗余表达        进行、对于、是否能够...
  超长句          >60字无断句
"""
import argparse
import json
import os
import re
import sys

import jieba

# ---------- 坏味词表（核心，可扩展） ----------
AI_CLICHE = [
    "总而言之", "综上所述", "值得注意的是", "众所周知", "毋庸置疑",
    "不难发现", "由此可见", "需要注意的是", "换句话说", "在这个充满",
    "赋能", "抓手", "闭环", "颗粒度", "底层逻辑", "方法论", "顶层设计",
    "多维度", "全链路", "一站式", "数字化赋能", "助力", "保驾护航",
    "delve", "it's worth noting", "in conclusion", "moreover",
]
FUZZY_WORDS = [
    "大概", "好像", "似乎", "也许", "或许", "差不多", "左右",
    "某些情况", "一定程度", "或多或少", "基本上", "几乎是",
    "maybe", "perhaps", "probably", "approximately",
]
EMPTY_EMPHASIS = [
    "非常", "十分", "极其", "超级", "真的", "简直", "绝对",
    "very", "really", "extremely", "literally", "actually",
]
REDUNDANT = [
    "进行", "对于", "是否能够", "予以", "加以", "作出",
    "在...方面", "相关事宜", "有关情况",
]
AI_HALLUCINATION_HEDGE = ["可能", "似乎", "在某种意义上", "某种程度上"]

# 可安全自动删除的 AI 腔引导词/填充词（删了语义无损）
AUTO_REMOVE = [
    "总而言之", "综上所述", "值得注意的是", "众所周知", "毋庸置疑",
    "不难发现", "由此可见", "需要注意的是", "换句话说",
    "it's worth noting", "in conclusion", "moreover",
]

WORD_BLACKLIST = {
    "AI味/废话填充": (AI_CLICHE, "warning"),
    "模糊词": (FUZZY_WORDS, "warning"),
    "空洞强调词": (EMPTY_EMPHASIS, "suggestion"),
}

# ---------- Markdown 处理 ----------
FENCE_RE = re.compile(r"^```|^~~~|^    ", re.M)


def strip_code_blocks(text):
    """把代码块/缩进代码替换为等行数空行（保留行号）"""
    lines = text.split("\n")
    out = []
    in_fence = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence or (line.startswith("    ") and not stripped.startswith("#")):
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def strip_front_matter(text):
    """去掉 YAML front matter（---...--- 开头块）"""
    if text.startswith("---"):
        end = text.find("\n---", 4)
        if end > 0:
            return text[end + 4:]
    return text


INLINE_PATTERNS = [
    (re.compile(r"`[^`\n]*`"), ""),                    # 行内代码
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),         # 图片
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),     # 链接 → 保留文字
    (re.compile(r"<[^>\n]+>"), ""),                    # HTML 标签
    (re.compile(r"<!--.*?-->", re.S), ""),             # 注释
    (re.compile(r"~~[^~\n]*~~"), ""),                  # 删除线
]


def clean_inline_markup(line):
    """清理行内 markup：代码/图片移除，链接保留文字"""
    for pat, repl in INLINE_PATTERNS:
        line = pat.sub(repl, line)
    return line


def split_sentences(text):
    """按中文句读标点切句"""
    return re.split(r"(?<=[。！？!?；;])", text)


# ---------- 检测 ----------
def check_words(line, line_no):
    """词表命中检测（jieba 分词后词级匹配 + 短语子串兜底）"""
    hits = []
    words = jieba.lcut(line)
    joined = line
    for cat, (wordlist, level) in WORD_BLACKLIST.items():
        for w in wordlist:
            # 词级匹配：分词结果含该词
            if len(w) <= 4 and w in words:
                col = joined.find(w)
                if col >= 0:
                    hits.append((line_no, col + 1, level, cat, w))
            # 短语兜底：直接子串（覆盖 jieba 切不开的长短语）
            elif len(w) > 4 and w in joined:
                col = joined.find(w)
                if col >= 0:
                    hits.append((line_no, col + 1, level, cat, w))
    return hits


def check_repetition(line, line_no):
    """相邻重复词检测（jieba 词级，忽略符号 token）"""
    import re as _re
    hits = []
    words = jieba.lcut(line)  # 原始序列，相邻判断不被过滤影响

    def is_content(w):
        return len(w) >= 2 and not _re.fullmatch(r"[\s\W_]+", w)

    for i in range(1, len(words)):
        if words[i] == words[i - 1] and is_content(words[i]):
            col = line.find(words[i])
            if col >= 0:
                hits.append((line_no, col + 1, "warning", "重复用词", f'"{words[i]}"连续重复'))
    return hits


def check_long_sentence(text):
    """超长句检测（跳过表格行）"""
    hits = []
    for line_no, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("#"):
            continue
        # 去掉行内行内代码和链接，按句读切分
        for s in split_sentences(stripped):
            s_clean = s.strip()
            if len(s_clean) > 60:
                hits.append((line_no, 1, "suggestion", "超长句", f"{len(s_clean)}字（>60），建议拆分"))
    return hits


def fix_text(text):
    """自动修复：删除可安全删除的 AI 腔引导词 + 中文重复词去重。
    安全规则：
      - 词后接"的/之/地/和/与"等（定语结构，如"综上所述的方案"）→ 不自动删
      - 词后接逗号/句读/行尾 → 删词并吞掉紧接的逗号
    返回 (修复后文本, changes[(行号, 说明)]). 不改代码块内容。"""
    lines = text.split("\n")
    out, changes = [], []
    in_fence = False
    for i, line in enumerate(lines, 1):
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        new = line
        for w in AUTO_REMOVE:
            idx = new.find(w)
            if idx < 0:
                continue
            tail = new[idx + len(w):].lstrip()
            # 定语结构保护：词后紧跟"的/之/地"等 → 跳过（句法复杂，留给人工）
            if tail.startswith(("的", "之", "地", "和", "与", "同", "及")):
                continue
            if tail.startswith(("，", ",", "、", "；", ";")):
                tail = tail[1:].lstrip()
            cand = new[:idx] + tail
            if cand != new:
                changes.append((i, f"删除 AI 腔「{w}」"))
                new = cand
        # 中文相邻重复词去重（如"真的真的"→"真的"，格式保真）
        cand = re.sub(r"([\u4e00-\u9fff]{2,8})\1", r"\1", new)
        if cand != new:
            changes.append((i, "重复词去重"))
            new = cand
        out.append(new)
    # 同行多 change 合并为一条注记（避免重复 diff）
    merged = []
    seen_lines = set()
    for line_no, note in changes:
        if line_no not in seen_lines:
            merged.append((line_no, note))
            seen_lines.add(line_no)
    return "\n".join(out), merged


def scan_file(fp):
    """扫描单个文件，返回 (file, hits)"""
    try:
        raw = open(fp, encoding="utf-8").read()
    except Exception as e:
        print(f"!! 无法读取 {fp}: {e}", file=sys.stderr)
        return fp, []
    text = strip_front_matter(raw)
    text = strip_code_blocks(text)
    lines = text.split("\n")
    hits = []
    cleaned_lines = []
    for i, line in enumerate(lines, 1):
        clean = clean_inline_markup(line)
        cleaned_lines.append(clean)
        hits += check_words(clean, i)
        hits += check_repetition(clean, i)
    hits += check_long_sentence("\n".join(cleaned_lines))
    hits.sort()
    return fp, hits


def main():
    parser = argparse.ArgumentParser(description="中文散文坏味检查器（jieba 分词 + 词表规则）")
    parser.add_argument("path", help="文件或目录")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--fix", action="store_true", help="修复模式：自动删除 AI 腔引导词/重复词，输出 diff")
    parser.add_argument("--apply", action="store_true", help="与 --fix 连用：将修复写回文件（先备份 .bak）")
    args = parser.parse_args()

    files = []
    if os.path.isfile(args.path):
        files = [args.path]
    else:
        for root, _, fs in os.walk(args.path):
            for f in fs:
                if f.endswith((".md", ".txt", ".rst")):
                    files.append(os.path.join(root, f))

    # ---- 修复模式 ----
    if args.fix:
        for fp in sorted(files):
            try:
                raw = open(fp, encoding="utf-8").read()
            except Exception as e:
                print(f"!! 无法读取 {fp}: {e}", file=sys.stderr)
                continue
            fixed, changes = fix_text(raw)
            if not changes:
                print(f"✅ {fp}: 无可自动修复项")
                continue
            print(f"--- {fp}: {len(changes)} 处自动修复 ---")
            raw_lines = raw.split("\n")
            for line_no, note in changes:
                old = raw_lines[line_no - 1].strip()
                new = fixed.split("\n")[line_no - 1].strip()
                print(f"  L{line_no} {note}")
                print(f"    - {old}")
                print(f"    + {new}")
            if args.apply:
                backup = fp + ".bak"
                open(backup, "w", encoding="utf-8").write(raw)
                open(fp, "w", encoding="utf-8").write(fixed)
                print(f"  ✍️ 已写回 {fp}（备份 {backup}）")
        # 修复后报告剩余（需人工/LLM 的：模糊词、强调词、超长句）
        print("\n=== 修复后剩余（需人工/LLM 处理）===")
        results = [scan_file(fp) for fp in sorted(files)]
        remaining = [(fp, h) for fp, h in results if h]
        if not remaining:
            print("✅ 全部干净")
        for fp, hits in remaining:
            for l, c, lv, cat, w in hits:
                print(f"{fp}:{l}:{c}  {lv:10s}  {cat}: {w}")
        return

    # ---- 纯 review 模式 ----
    results = [scan_file(fp) for fp in sorted(files)]

    if args.json:
        out = [{"file": fp, "line": l, "col": c, "level": lv, "type": cat, "detail": w}
               for fp, hits in results for (l, c, lv, cat, w) in hits]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    for fp, hits in results:
        for l, c, lv, cat, w in hits:
            print(f"{fp}:{l}:{c}  {lv:10s}  {cat}: {w}")
    total = sum(len(h) for _, h in results)
    if total:
        per = "  ".join(f"{os.path.basename(fp)}: {len(h)}" for fp, h in results if h)
        print(f"\n✖ {total} 个坏味（{per}）")
    else:
        print("✅ 未发现坏味")


if __name__ == "__main__":
    main()
