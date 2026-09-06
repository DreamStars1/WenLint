"""回归测试：Markdown mask / 行号列号 / front matter 保行。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wenlint.engine import scan_text, mask_text, fix_text  # noqa: E402

BASE = os.path.dirname(__file__)


def f(text):
    return [(x["line"], x["col"], x["rule_id"]) for x in scan_text(text)]


def test_front_matter_keeps_line_numbers():
    text = "---\ntitle: x\ndate: 2026\n---\n\n总而言之，方案好。\n"
    hits = f(text)
    assert (6, 1, "C001") in hits, f"行号应在 6（front matter 4 行 + 空行），实际 {hits}"


def test_inline_code_masked():
    text = "看这段 `总而言之` 代码不报，但后面的 总而言之 要报。\n"
    hits = f(text)
    assert len(hits) == 1 and hits[0][0] == 1
    assert hits[0][2] == "C001"
    # 列号应指向第二个"总而言之"（行内代码里的被等长 mask 跳过）
    end_code = text.index("`", text.index("`") + 1) + 1  # 反引号对结束位置
    expected = text.index("总而言之", end_code) + 1
    assert hits[0][1] == expected, f"列号应为 {expected}，实际 {hits[0][1]}"


def test_code_block_masked():
    text = "```python\n总而言之 非常 大概\n```\n正文 总而言之。\n"
    hits = f(text)
    assert len(hits) == 1 and hits[0][0] == 4


def test_url_masked_but_link_text_checked():
    text = "[文字大概](https://x.com/总而言之)\n"
    hits = f(text)
    assert len(hits) == 1
    assert hits[0][2] == "H001"  # 只有链接文字里的"大概"，URL 里的不报


def test_quote_content_protected_in_review():
    text = "我把“总而言之”当例子，但 总而言之 是真的套话。\n"
    hits = f(text)
    c001 = [h for h in hits if h[2] == "C001"]
    assert len(c001) == 1  # 只有引号外那个


def test_duplicate_word_col_precise():
    text = "问题真的真的很严重。\n"
    hits = f(text)
    d001 = [h for h in hits if h[2] == "D001"]
    assert d001 and d001[0][1] == len("问题") + 1


def test_mask_equal_length():
    text = "a `code` b [x](http://y.cn) c\n"
    masked = mask_text(text)
    assert len(masked) == len(text), "mask 必须等长（保列号）"
    line = masked.split("\n")[0]
    # 行内代码/URL 内容被空格替代，但链接文字 x 保留
    assert "code" not in line and "y.cn" not in line
    assert "x" in line


def test_academic_profile_disables_hedge_soft():
    from wenlint.profiles import PROFILES
    assert "H002" in PROFILES["academic"]["disable"]
    text = "可能或许需要审慎。\n"
    hits_gen = f(text)
    hits_ac = [(x[0], x[1], x[2]) for x in scan_text(text, profile="academic")]
    assert any(h[2] == "H002" for h in hits_gen)
    assert not any(h[2] == "H002" for h in hits_ac)


def test_leftright_block_space_sense():
    text = "这个桌子的左右两边都有东西，大约 3 米左右。\n"
    hits = [h for h in f(text) if h[2] == "H003"]
    # "左右边"被 block；"3 米左右"的左右该报
    assert len(hits) == 1
