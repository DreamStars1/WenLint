"""S001 exact spans and Feishu hard block-boundary regressions."""
from __future__ import annotations

import dataclasses

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.findings import bind_findings
from wenlint.feishu.projection import project_xml
from wenlint.scanner import scan_text

REF = dataclasses.replace(
    parse_document_ref("https://acme.feishu.cn/docx/DocToken"),
    document_id="DocToken",
    canonical_url="https://acme.feishu.cn/docx/DocToken",
)


def _long_sentence() -> str:
    return (
        "这是一句需要明显超过八十个汉字阈值的中文长句用于验证超长句规则能够返回精确原文范围"
        "并且在单一可写文本节点中完成安全绑定所以继续补充足够多的正文内容直到远远超过阈值。"
    )


def test_s001_match_is_exact_nonempty_substring():
    text = _long_sentence() + "\n"
    hits = [h for h in scan_text(text) if h["rule_id"] == "S001"]
    assert len(hits) == 1
    assert hits[0]["match"]
    assert hits[0]["match"] == hits[0]["sentence"]
    assert hits[0]["match"] in text
    assert text[hits[0]["col"] - 1 :].startswith(hits[0]["match"][:8])


def test_s001_single_feishu_paragraph_is_exact_and_writable():
    sentence = _long_sentence()
    xml = f'<p id="blkLong">{sentence}</p>'
    snapshot = project_xml(xml, REF, 1)
    raw = [h for h in scan_text(snapshot.projection) if h["rule_id"] == "S001"]
    assert len(raw) == 1
    assert raw[0]["match"] == sentence
    public = [
        {
            "rule": item["rule_id"],
            "type": "lint",
            "severity": item["severity"],
            "category": item["category"],
            "message": item["message"],
            "review_hint": item["review_hint"],
            "line": item["line"],
            "column": item["col"],
            "text": item["match"],
            "sentence": item["sentence"],
            "before": None,
            "after": None,
        }
        for item in raw
    ]
    bound = bind_findings(snapshot, public)
    assert len(bound) == 1
    assert bound[0].location.mapping_status == "exact"
    assert bound[0].location.writable is True
    assert bound[0].location.block_id == "blkLong"


def test_s001_rich_text_cross_node_is_not_writable():
    left = "这是一句需要明显超过八十个汉字阈值的中文长句用于验证跨节点边界时前半段"
    right = (
        "后半段继续补充足够多的正文内容并且必须降级为不可写映射"
        "所以整句长度要远远超过八十个汉字的文档阈值。"
    )
    xml = f'<p id="blkRich">{left}<b>{right}</b></p>'
    snapshot = project_xml(xml, REF, 1)
    raw = [h for h in scan_text(snapshot.projection) if h["rule_id"] == "S001"]
    assert len(raw) == 1
    assert len(raw[0]["match"]) > 80
    public = [
        {
            "rule": item["rule_id"],
            "type": "lint",
            "severity": item["severity"],
            "category": item["category"],
            "message": item["message"],
            "review_hint": item["review_hint"],
            "line": item["line"],
            "column": item["col"],
            "text": item["match"],
            "sentence": item["sentence"],
            "before": None,
            "after": None,
        }
        for item in raw
    ]
    bound = bind_findings(snapshot, public)
    assert bound[0].location.writable is False
    assert bound[0].location.mapping_status == "cross_node"


def test_adjacent_feishu_paragraphs_are_not_merged_into_one_s001():
    first = "这是第一段独立飞书段落，长度明显低于八十汉字阈值。"
    second = "这是第二段独立飞书段落，长度同样低于八十汉字阈值。"
    xml = f'<p id="a">{first}</p><p id="b">{second}</p>'
    snapshot = project_xml(xml, REF, 1)
    assert "\n\n" in snapshot.projection
    hits = [h for h in scan_text(snapshot.projection) if h["rule_id"] == "S001"]
    assert hits == []


def test_local_markdown_soft_wrap_still_aggregates_long_sentence():
    first = "这是一句跨行书写的中文长句用于验证上下文能够完整保留"
    second = "第二行继续补充足够多的正文内容直到总长度超过五十字阈值并在这里结束。"
    hits = [
        h
        for h in scan_text(f"{first}\n{second}\n", profile="instruction")
        if h["rule_id"] == "S001"
    ]
    assert len(hits) == 1
    assert hits[0]["match"] == f"{first}\n{second}"
    assert hits[0]["sentence"] == hits[0]["match"]
