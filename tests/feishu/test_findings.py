"""Tests for scanner finding → Feishu SourceMap binding."""
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

SIMPLE_XML = (
    '<h1 block-id="blkTitle">标题</h1>'
    '<p block-id="blkParagraph">普通正文可能含糊。</p>'
)

CROSS_NODE_XML = (
    '<p block-id="blkCross"><b>可</b><i>能</i>含糊。</p>'
)

CROSS_NODE_FINDINGS = [
    {
        "rule": "H002",
        "type": "candidate",
        "severity": "candidate",
        "category": "hedge",
        "message": "可能",
        "review_hint": "check",
        "line": 1,
        "column": 1,
        "text": "可能",
        "sentence": "可能含糊。",
        "before": None,
        "after": None,
    }
]


def test_binds_exact_single_node_finding():
    snapshot = project_xml(SIMPLE_XML, REF, 4)
    findings = scan_text(snapshot.projection)
    public = [
        {
            "rule": f["rule_id"],
            "type": "candidate" if f["severity"] == "candidate" else "lint",
            "severity": f["severity"],
            "category": f["category"],
            "message": f["message"],
            "review_hint": f["review_hint"],
            "line": f["line"],
            "column": f["col"],
            "text": f["match"],
            "sentence": f["sentence"],
            "before": None,
            "after": None,
        }
        for f in findings
    ]
    bound = bind_findings(snapshot, public)
    target = next(item for item in bound if item.rule == "H002")
    assert target.location.mapping_status == "exact"
    assert target.location.block_id == "blkParagraph"
    assert target.location.writable is True


def test_cross_inline_node_is_report_only():
    bound = bind_findings(project_xml(CROSS_NODE_XML, REF, 4), CROSS_NODE_FINDINGS)
    assert bound[0].location.writable is False
    assert bound[0].location.reason == "cross_node"


def test_synthetic_span_is_not_writable():
    snapshot = project_xml(SIMPLE_XML, REF, 4)
    findings = [
        {
            "rule": "X001",
            "type": "lint",
            "severity": "warning",
            "category": "x",
            "message": "hash",
            "review_hint": "",
            "line": 1,
            "column": 1,
            "text": "#",
            "sentence": "# 标题",
            "before": None,
            "after": None,
        }
    ]
    bound = bind_findings(snapshot, findings)
    assert bound[0].location.writable is False
    assert bound[0].location.reason in {"synthetic_span", "unmapped"}
