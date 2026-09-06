"""Tests for secure XML projection and SourceMap construction."""
from __future__ import annotations

from pathlib import Path

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.models import Patch
from wenlint.feishu.projection import (
    XmlSafetyError,
    find_block,
    parse_blocks,
    project_xml,
    replace_node_text,
    resolve_text_target,
    serialize_block,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_XML = (FIXTURES / "structured_document.xml").read_text(encoding="utf-8")
REF = parse_document_ref("https://acme.feishu.cn/docx/DocToken")
REF = REF.__class__(
    input_url=REF.input_url,
    kind=REF.kind,
    input_token=REF.input_token,
    document_id="DocToken",
    canonical_url=REF.input_url,
)


def test_projection_preserves_scanner_roles():
    snapshot = project_xml(FIXTURE_XML, REF, revision_id=7)
    lines = snapshot.projection.splitlines()
    assert "# 一级标题" in lines
    assert "普通正文可能含糊。" in lines
    assert "- 列表正文" in lines
    assert "> 引用正文" in lines
    assert "https://internal.example" not in snapshot.projection
    assert "链接文字" in snapshot.projection


@pytest.mark.parametrize("payload", ["<!DOCTYPE x>", "<!ENTITY x SYSTEM 'file:///x'>"])
def test_rejects_dtd_and_entities(payload):
    with pytest.raises(XmlSafetyError):
        project_xml(payload, REF, revision_id=1)


def test_rejects_oversized_and_malformed_xml():
    with pytest.raises(XmlSafetyError):
        project_xml("x" * (20 * 1024 * 1024 + 1), REF, revision_id=1)
    with pytest.raises(XmlSafetyError):
        project_xml("<p>unterminated", REF, revision_id=1)


def test_synthetic_prefixes_are_not_writable():
    snapshot = project_xml(FIXTURE_XML, REF, revision_id=7)
    hash_spans = [
        span
        for span in snapshot.source_map
        if snapshot.projection[span.projection_start : span.projection_end].startswith(
            "#"
        )
        and span.block_id is None
    ]
    assert hash_spans
    assert all(not span.writable for span in hash_spans)


def test_visible_text_maps_to_block_and_offsets():
    snapshot = project_xml(FIXTURE_XML, REF, revision_id=7)
    target = "普通正文可能含糊。"
    start = snapshot.projection.index(target)
    spans = [
        span
        for span in snapshot.source_map
        if span.projection_start >= start and span.projection_end <= start + len(target)
    ]
    assert spans
    assert all(span.block_id == "blkParagraph" for span in spans)
    assert all(span.writable for span in spans)
    assert all(span.node_path is not None for span in spans)


def test_serialize_and_replace_round_trip():
    snapshot = project_xml(FIXTURE_XML, REF, revision_id=7)
    original = serialize_block(snapshot, "blkParagraph")
    assert "普通正文可能含糊。" in original
    patch = Patch(
        patch_id="p1",
        section_locator="一级标题[1]",
        section_fingerprint="x",
        block_id="blkParagraph",
        node_path=(),
        source_start=0,
        source_end=len("普通正文可能含糊。"),
        before="普通正文可能含糊。",
        after="普通正文已经明确。",
        rule_id="H002",
        rationale="clarify",
    )
    patched = replace_node_text(snapshot, patch)
    assert "普通正文已经明确。" in patched
    assert "普通正文可能含糊。" not in patched


def test_title_metadata_is_excluded_from_projection():
    xml = "<title>metadata</title><p block-id=\"p\">正文。</p>"
    snapshot = project_xml(xml, REF, revision_id=1)
    assert "metadata" not in snapshot.projection
    assert snapshot.projection == "正文。"
    assert all(span.block_id != "title" for span in snapshot.source_map)


@pytest.mark.parametrize(
    ("xml", "first_marker", "second_marker"),
    [
        (
            '<ol block-id="list"><li><p>甲。</p></li><li><p>乙。</p></li></ol>',
            "1. ",
            "2. ",
        ),
        (
            '<ul block-id="list"><li><p>甲。</p></li><li><p>乙。</p></li></ul>',
            "- ",
            "- ",
        ),
    ],
)
def test_top_level_lists_project_markers_and_writable_container_spans(
    xml, first_marker, second_marker
):
    snapshot = project_xml(xml, REF, revision_id=1)
    assert snapshot.projection == f"{first_marker}甲。\n{second_marker}乙。"
    text_spans = [
        span
        for span in snapshot.source_map
        if snapshot.projection[span.projection_start : span.projection_end]
        in {"甲。", "乙。"}
    ]
    assert len(text_spans) == 2
    assert all(span.writable and span.block_id == "list" for span in text_spans)
    root = parse_blocks(xml)
    block = find_block(root, "list")
    for span, expected in zip(text_spans, ("甲。", "乙。"), strict=True):
        node, is_tail = resolve_text_target(block, span.node_path)
        actual = (node.tail if is_tail else node.text) or ""
        assert actual[span.source_start : span.source_end] == expected


def test_list_without_safe_top_level_id_stays_nonwritable():
    xml = "<ol><li><p>甲。</p></li><li><p>乙。</p></li></ol>"
    snapshot = project_xml(xml, REF, revision_id=1)
    assert "甲。" in snapshot.projection and "乙。" in snapshot.projection
    text_spans = [
        span
        for span in snapshot.source_map
        if snapshot.projection[span.projection_start : span.projection_end]
        in {"甲。", "乙。"}
    ]
    assert text_spans
    assert all(not span.writable for span in text_spans)


def test_callout_simple_paragraph_is_writable_on_container():
    xml = '<callout block-id="c"><p>正文。</p></callout>'
    snapshot = project_xml(xml, REF, revision_id=1)
    assert snapshot.projection == "正文。"
    spans = [
        span
        for span in snapshot.source_map
        if snapshot.projection[span.projection_start : span.projection_end] == "正文。"
    ]
    assert len(spans) == 1
    span = spans[0]
    assert span.writable is True
    assert span.block_id == "c"
    node, is_tail = resolve_text_target(find_block(parse_blocks(xml), "c"), span.node_path)
    actual = (node.tail if is_tail else node.text) or ""
    assert actual[span.source_start : span.source_end] == "正文。"
    assert is_tail is False


def test_br_becomes_synthetic_newline_between_text():
    xml = '<p block-id="p">甲<br/>乙</p>'
    snapshot = project_xml(xml, REF, revision_id=1)
    assert "甲\n乙" in snapshot.projection
    assert snapshot.projection == "甲\n乙"
    newline_spans = [
        span
        for span in snapshot.source_map
        if snapshot.projection[span.projection_start : span.projection_end] == "\n"
    ]
    assert len(newline_spans) == 1
    assert newline_spans[0].writable is False
    assert newline_spans[0].block_id is None
    assert newline_spans[0].node_path is None
    text_spans = [
        span
        for span in snapshot.source_map
        if snapshot.projection[span.projection_start : span.projection_end] in {"甲", "乙"}
    ]
    assert all(span.writable and span.block_id == "p" for span in text_spans)


@pytest.mark.parametrize(
    "tag",
    ["synced_reference", "synced_source", "synced-reference", "synced-source"],
)
def test_synced_resource_subtrees_never_enter_projection(tag):
    xml = (
        f'<{tag} block-id="s"><p>隐藏正文。</p></{tag}>'
        '<p block-id="p">可见正文。</p>'
        f'<p block-id="t">前<{tag}>内隐</{tag}>后尾</p>'
    )
    snapshot = project_xml(xml, REF, revision_id=1)
    assert "隐藏正文。" not in snapshot.projection
    assert "内隐" not in snapshot.projection
    assert "可见正文。" in snapshot.projection
    assert "前" in snapshot.projection and "后尾" in snapshot.projection
    assert all(span.block_id != "s" for span in snapshot.source_map)
    assert not any(span.writable and "隐" in (
        snapshot.projection[span.projection_start : span.projection_end]
    ) for span in snapshot.source_map)


def test_inline_tails_remain_writable_after_emphasis():
    xml = '<p block-id="p">甲<em>中</em>尾</p>'
    snapshot = project_xml(xml, REF, revision_id=1)
    assert snapshot.projection == "甲中尾"
    by_text = {
        snapshot.projection[span.projection_start : span.projection_end]: span
        for span in snapshot.source_map
    }
    assert by_text["甲"].writable and by_text["甲"].node_path == ()
    assert by_text["中"].writable and by_text["中"].node_path == (0,)
    assert by_text["尾"].writable and by_text["尾"].node_path == (0, -1)
