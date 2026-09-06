"""回归测试：Markdown mask / 行号列号 / front matter 保行。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wenlint.markdown import mask_text  # noqa: E402
from wenlint.scanner import scan_text  # noqa: E402

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


def test_quote_content_checked_in_review():
    """引号内正文照常检查（元语境示例词由语义层判 KEEP，规则层不静默放过）"""
    text = "我把“总而言之”当例子，但 总而言之 是真的套话。\n"
    hits = f(text)
    c001 = [h for h in hits if h[2] == "C001"]
    assert len(c001) == 2, "引号内外的套话都该报（共 2 处）"


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


def test_s001_scope_paragraph_only():
    """vale 借鉴：S001 只判散文段落，列表/导航行豁免"""
    text = ("- `ref/x.md` — 这是很长的导航行超过八十个字符阈值但它是列表结构不是句子不该被当成超长句处理\n\n"
            "这是普通散文段落它的长度需要超过八十个字符的文档阈值才会被判定为超长句，这一句写得很长就是为了让测试文本真的超过八十个字符从而触发超长句提示并验证列表导航行不会被误判成句子\n")
    s001 = [h for h in scan_text(text) if h["rule_id"] == "S001"]
    assert len(s001) == 1 and s001[0]["line"] == 3, f"应只报段落行, got {s001}"


def test_s001_bold_markers_not_counted():
    """** 粗体标记不计入句长"""
    # 文本 48 字 + 4 个 ** 标记 = 52 raw 字符；剥标记后 < 50 不报（instruction）
    body = "这段内容共四十八个字，加上加粗符号也不该因为标记字符而被判定超长，所以这条应该保持干净"
    text = f"**{body}**\n"
    from wenlint.profiles import PROFILES
    hits = scan_text(text, profile="instruction", filename="SKILL.md")
    assert not [h for h in hits if h["rule_id"] == "S001"], "粗体标记不应计入句长"


# ===== 审查 P0 回归：Markdown scope 行为 =====

def test_heading_not_reported():
    """标题行是结构不是散文，套话词不报"""
    text = "# 总而言之，这是标题\n\n正文没有套话。\n"
    hits = f(text)
    assert not [h for h in hits if h[2] == "C001"], "heading 行不应报词规则"


def test_fenced_code_not_reported():
    """代码块内的词不报"""
    text = "正文。\n```\n总而言之 在代码里\n```\n正文二。\n"
    hits = f(text)
    assert not [h for h in hits if h[2] == "C001"]


def test_indented_code_not_reported():
    """四空格缩进代码块内的词不报"""
    text = "正文。\n\n    总而言之 缩进代码\n\n正文二。\n"
    hits = f(text)
    assert not [h for h in hits if h[2] == "C001"]


def test_multi_line_html_comment_not_reported():
    """多行 HTML 注释内容不报"""
    text = "正文。\n<!--\n总而言之 在注释里\n可能 也在\n-->\n正文二。\n"
    hits = f(text)
    assert not [h for h in hits if h[2] == "C001"]
    assert not [h for h in hits if h[2] == "H002"]


def test_paren_content_checked():
    """括号内正文照常检查（不再静默保护）"""
    text = "（这个方案可能有问题）\n"
    hits = f(text)
    assert any(h[2] == "H002" for h in hits), "括号内正文应被检查"


def test_link_col_not_shifted():
    """链接文字列号精确：文字不被 [ 前移"""
    text = "[文字大概](https://example.com)\n"
    hits = f(text)
    h001 = [h for h in hits if h[2] == "H001"]
    assert h001 and h001[0][1] == 4, f"大概应从第 4 列开始，实际 {h001[0][1] if h001 else None}"


def test_same_rule_two_hits_both_kept():
    """同规则同句两处命中都保留（不按行合并吞命中）"""
    text = "这个大概正确。另一个好像错误。\n"
    hits = f(text)
    h001 = [h for h in hits if h[2] == "H001"]
    assert len(h001) == 2, f"大概+好像都应报，实际 {len(h001)}"


def test_cliche_attributive_not_reported():
    """C001 定语结构（综上所述的方案）不报 warning"""
    text = "综上所述的方案需要人工判断。\n"
    hits = f(text)
    assert not [h for h in hits if h[2] == "C001"], "定语结构套话不报"


def test_english_text_with_chinese_segment():
    """英文为主的文本中的中文片段仍被检查（无文件级语言守卫）"""
    text = ("This is an English README paragraph that is fairly long and contains "
            "technical terms. 总而言之，这里有中文套话。\n")
    hits = f(text)
    assert any(h[2] == "C001" for h in hits), "英文文件中的中文段应被检查"
