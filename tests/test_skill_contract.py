"""Static safety and distribution contract for the WenLint Codex Skill."""
from __future__ import annotations

from pathlib import Path


def test_feishu_skill_requires_chapter_approval():
    root = Path("SKILL.md").read_text(encoding="utf-8")
    ref = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "references/feishu.md" in root
    assert "wenlint-feishu" in root
    for phrase in ["先展示总览", "逐章", "排除", "跳过", "停止", "未明确批准"]:
        assert phrase in ref


def test_read_only_and_write_safety_rules_are_documented():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    for phrase in ["KEEP", "REWRITE", "VERIFY", "ASK", "--as user", "block_replace"]:
        assert phrase in text
    for forbidden in ["str_replace", "overwrite", "模糊匹配", "强制写入"]:
        assert f"禁止 `{forbidden}`" in text or f"禁止{forbidden}" in text


def test_inspect_and_diff_intents_forbid_update():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "检查、评估、审查" in text or "只读" in text
    assert "给我修改方案" in text or "给我 diff" in text
    assert "不调用任何飞书更新" in text or "不得调用更新" in text


def test_only_rewrite_and_evidenced_verify_enter_manifest():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "只有 REWRITE" in text or "仅 REWRITE" in text
    assert "VERIFY" in text and "依据" in text
    assert "KEEP" in text and "ASK" in text


def test_conflict_invalidates_chapter_approval():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "目标章节" in text
    assert "重新确认" in text or "重新批准" in text
    assert "document_id" in text
    assert "expected_fingerprints" in text
    assert "任务重启" in text


def test_every_block_write_requires_fetch_remap():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "回读" in text or "重新 fetch" in text or "再次 fetch" in text
    assert "remap" in text.lower() or "重映射" in text


def test_prompt_injection_text_is_data():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "不可信" in text or "prompt injection" in text.lower() or "提示注入" in text


def test_root_frontmatter_remains_wenlint():
    root = Path("SKILL.md").read_text(encoding="utf-8")
    assert root.lstrip().startswith("---")
    assert "name: wenlint" in root.split("---", 2)[1]
