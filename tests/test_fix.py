"""回归测试：fix 安全（Markdown-safe、引号保护、定语结构保护、预览正确性）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wenlint.fixer import fix_text  # noqa: E402
from wenlint.scanner import scan_text  # noqa: E402


def test_fix_removes_leading_cliche():
    text = "总而言之，方案很好。\n"
    fixed, changes = fix_text(text)
    assert fixed == "方案很好。\n"
    assert len(changes) == 1


def test_fix_never_touches_inline_code():
    text = "看 `总而言之` 这段代码，然后 总而言之，改这里。\n"
    fixed, changes = fix_text(text)
    assert "`总而言之`" in fixed, "行内代码里的词被删了！"
    assert "总而言之，改这里" not in fixed
    assert len(changes) == 1


def test_fix_never_touches_code_block():
    text = "```\n总而言之\n```\n总而言之，正文。\n"
    fixed, changes = fix_text(text)
    lines = fixed.split("\n")
    assert lines[1] == "总而言之", "代码块内容被修改！"
    assert "总而言之，正文" not in fixed


def test_fix_never_touches_quotes():
    text = "我把“总而言之”作为例子，正文 总而言之，删我。\n"
    fixed, changes = fix_text(text)
    assert "“总而言之”" in fixed, "引号里的示例词被删了！"
    assert len(changes) == 1


def test_fix_protects_attributive_structure():
    text = "综上所述的方案需要保留。总而言之，这个能删。\n"
    fixed, changes = fix_text(text)
    assert "综上所述的方案" in fixed, "定语结构被破坏！"
    assert "总而言之，这个能删" not in fixed
    assert len(changes) == 1


def test_fix_remaining_based_on_fixed_text():
    """P0 回归：--fix 后剩余必须扫描修复后文本（未 apply 时）。
    验证方式：修复前"非常"在 col 10，删除套话后 col 前移——剩余列表列号应反映修复后。"""
    text = "总而言之，这个方案非常好。\n"
    fixed, _ = fix_text(text)
    remaining = [x for x in scan_text(fixed) if x["rule_id"] == "E001"]
    assert remaining and remaining[0]["col"] == len("这个方案") + 1, \
        f"剩余应基于修复后文本（col 前移），实际 col={remaining[0]['col'] if remaining else None}"


def test_fix_idempotent_second_run_no_changes():
    text = "总而言之，方案很好。\n总而言之，继续。\n"
    fixed, changes = fix_text(text)
    assert len(changes) == 2
    fixed2, changes2 = fix_text(fixed)
    assert changes2 == []


def test_fix_whitelist_only_high_confidence():
    """fix 只处理白名单（C001/C003/R002）；D001 重复词留给人工。"""
    text = "真的真的很好。\n"
    fixed, changes = fix_text(text)
    assert changes == [], "D001 不应被自动删（语义风险，留给人工）"
