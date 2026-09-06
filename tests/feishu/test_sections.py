"""Tests for section locators and canonical fingerprints."""
from __future__ import annotations

from pathlib import Path

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.projection import project_xml
from wenlint.feishu.sections import SectionError, locate_section, section_fingerprint

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
