"""Tests for secure XML projection and SourceMap construction."""
from __future__ import annotations

from pathlib import Path

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.models import Patch
from wenlint.feishu.projection import (
    XmlSafetyError,
    project_xml,
    replace_node_text,
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
