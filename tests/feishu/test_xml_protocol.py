"""Tests for Feishu XML block-id dialect normalization."""
from __future__ import annotations

import dataclasses
from xml.etree.ElementTree import fromstring

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.findings import bind_findings
from wenlint.feishu.projection import find_block, parse_blocks, project_xml
from wenlint.feishu.xml_protocol import XmlProtocolError, block_id_of
from wenlint.scanner import scan_text

REF = dataclasses.replace(
    parse_document_ref("https://acme.feishu.cn/docx/DocToken"),
    document_id="DocToken",
    canonical_url="https://acme.feishu.cn/docx/DocToken",
)


@pytest.mark.parametrize("attr", ["id", "block-id", "block_id"])
def test_block_id_of_accepts_each_dialect(attr):
    element = fromstring(f'<p {attr}="blkA">正文</p>')
    assert block_id_of(element) == "blkA"


def test_block_id_of_same_values_across_attrs_are_ok():
    element = fromstring('<p id="blkA" block-id="blkA" block_id="blkA">正文</p>')
    assert block_id_of(element) == "blkA"


def test_block_id_of_conflicting_values_fail_closed():
    element = fromstring('<p id="a" block-id="b">正文</p>')
    with pytest.raises(XmlProtocolError) as exc:
        block_id_of(element)
    assert exc.value.kind == "ambiguous_block_id"


@pytest.mark.parametrize("attr", ["id", "block-id", "block_id"])
def test_projection_sections_and_find_block_equivalent_across_id_dialects(attr):
    xml = (
        f'<h1 {attr}="blkTitle">产品设计</h1>'
        f'<p {attr}="blkParagraph">普通正文可能含糊。</p>'
    )
    snapshot = project_xml(xml, REF, 1)
    assert snapshot.sections[0].block_ids == ("blkTitle", "blkParagraph")
    assert any(span.block_id == "blkParagraph" for span in snapshot.source_map)
    block = find_block(parse_blocks(xml), "blkParagraph")
    assert block_id_of(block) == "blkParagraph"


def test_id_dialect_change_does_not_change_fingerprint():
    left = project_xml('<p block-id="a">正文可能含糊。</p>', REF, 1)
    right = project_xml('<p id="b">正文可能含糊。</p>', REF, 2)
    assert left.sections[0].fingerprint == right.sections[0].fingerprint


def test_modern_id_finding_binds_writable_section():
    xml = '<h1 id="t">标题</h1><p id="p1">普通正文可能含糊。</p>'
    snapshot = project_xml(xml, REF, 1)
    raw = scan_text(snapshot.projection, profile="formal")
    public = [
        {
            "rule": item["rule_id"],
            "type": "candidate" if item["severity"] == "candidate" else "lint",
            "severity": item["severity"],
            "category": item["category"],
            "message": item["message"],
            "review_hint": item["review_hint"],
            "line": item["line"],
            "column": item["col"],
            "text": item["match"],
            "sentence": item.get("sentence", ""),
            "before": None,
            "after": None,
        }
        for item in raw
    ]
    bound = bind_findings(snapshot, public)
    hedge = [item for item in bound if item.rule.startswith("H")]
    assert hedge
    assert hedge[0].location.writable is True
    assert hedge[0].location.mapping_status == "exact"
    assert hedge[0].location.block_id == "p1"
    assert hedge[0].section is not None
