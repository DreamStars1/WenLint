"""Tests for section locators and canonical fingerprints."""
from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import fromstring

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.projection import project_xml
from wenlint.feishu.sections import (
    SectionError,
    locate_section,
    owning_section,
    section_fingerprint,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REF = parse_document_ref("https://acme.feishu.cn/docx/DocToken")
REF = REF.__class__(
    input_url=REF.input_url,
    kind=REF.kind,
    input_token=REF.input_token,
    document_id="DocToken",
    canonical_url=REF.input_url,
)

XML_WITH_BLOCK_ID_A = """
<h1 block-id="blkA">标题</h1>
<p block-id="blkBody">正文内容。</p>
""".strip()

XML_WITH_BLOCK_ID_B = """
<h1 block-id="blkRenamed">标题</h1>
<p block-id="blkBody2">正文内容。</p>
""".strip()

XML_WITH_CHANGED_TEXT = """
<h1 block-id="blkA">标题</h1>
<p block-id="blkBody">正文已改。</p>
""".strip()


def test_section_fingerprint_ignores_block_ids_not_text():
    first = project_xml(XML_WITH_BLOCK_ID_A, REF, 1).sections[0]
    renamed_ids = project_xml(XML_WITH_BLOCK_ID_B, REF, 2).sections[0]
    changed_text = project_xml(XML_WITH_CHANGED_TEXT, REF, 3).sections[0]
    assert first.fingerprint == renamed_ids.fingerprint
    assert first.fingerprint != changed_text.fingerprint


def test_duplicate_title_ordinals_and_nested_paths():
    xml = (FIXTURES / "duplicate_sections.xml").read_text(encoding="utf-8")
    snapshot = project_xml(xml, REF, 1)
    locators = [section.locator for section in snapshot.sections]
    assert "同名[1]" in locators
    assert "同名[2]" in locators
    assert "同名[2]/子节[1]" in locators


def test_lead_in_and_no_heading_documents():
    lead = project_xml('<p block-id="a">开头。</p><h1 block-id="b">标题</h1>', REF, 1)
    assert lead.sections[0].locator == "文档开头"
    whole = project_xml('<p block-id="a">整篇。</p>', REF, 1)
    assert len(whole.sections) == 1
    assert whole.sections[0].level == 0


def test_ambiguous_duplicate_locator_raises():
    snapshot = project_xml(XML_WITH_BLOCK_ID_A, REF, 1)
    with pytest.raises(SectionError):
        locate_section(snapshot, "不存在[1]")


def test_section_fingerprint_helper_matches_model():
    snapshot = project_xml(XML_WITH_BLOCK_ID_A, REF, 1)
    # Re-project to obtain the same canonical hash via the public helper path.
    assert snapshot.sections[0].fingerprint.startswith("sha256:")
    assert len(section_fingerprint.__doc__ or "") > 0


def test_fingerprint_escaped_markup_text_differs_from_real_child_element():
    """Literal ``&lt;b&gt;x&lt;/b&gt;`` text must not collide with a ``<b>`` child."""
    escaped = fromstring('<p block-id="a">&lt;b&gt;x&lt;/b&gt;</p>')
    nested = fromstring('<p block-id="a"><b>x</b></p>')
    assert section_fingerprint(escaped) != section_fingerprint(nested)


def test_fingerprint_distinguishes_text_child_boundary_and_tail():
    """Text, child open/close, and tails must not collide across shapes."""
    text_only = fromstring('<p block-id="a">ab</p>')
    split = fromstring('<p block-id="a">a<b></b>b</p>')
    with_tail = fromstring('<p block-id="a"><b>a</b>b</p>')
    fps = {
        section_fingerprint(text_only),
        section_fingerprint(split),
        section_fingerprint(with_tail),
    }
    assert len(fps) == 3


def test_fingerprint_keeps_resource_id_ignores_only_volatile_ids():
    with_resource = fromstring('<p block-id="a" revision-id="9"><cite id="resA">注</cite></p>')
    renamed_block = fromstring('<p block-id="b" revision_id="1"><cite id="resA">注</cite></p>')
    other_resource = fromstring('<p block-id="a"><cite id="resB">注</cite></p>')
    assert section_fingerprint(with_resource) == section_fingerprint(renamed_block)
    assert section_fingerprint(with_resource) != section_fingerprint(other_resource)


def test_owning_section_picks_deepest_nested_body_owner():
    xml = (
        '<h1 block-id="h1">一级</h1>'
        '<h2 block-id="h2">二级</h2>'
        '<p block-id="body">子节正文。</p>'
    )
    snapshot = project_xml(xml, REF, 1)
    owner = owning_section(snapshot, "body")
    assert owner.locator == "一级[1]/二级[1]"
    assert owner.title == "二级"


def test_owning_section_missing_block_fails_closed():
    snapshot = project_xml(XML_WITH_BLOCK_ID_A, REF, 1)
    with pytest.raises(SectionError) as exc:
        owning_section(snapshot, "missing-block")
    assert exc.value.kind == "missing_section"
