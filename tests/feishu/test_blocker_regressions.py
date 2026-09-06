"""Regression tests for Feishu 0.2 acceptance blockers."""
from __future__ import annotations

import dataclasses

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.findings import bind_findings
from wenlint.feishu.models import ApprovedSectionPlan, InspectionReport, Patch
from wenlint.feishu.patches import (
    PatchValidationError,
    apply_approved_section,
    validate_patches,
)
from wenlint.feishu.projection import project_xml, resolve_text_target, find_block, parse_blocks
from wenlint.feishu.sections import build_sections

REF = dataclasses.replace(
    parse_document_ref("https://acme.feishu.cn/docx/DocToken"),
    document_id="DocToken",
    canonical_url="https://acme.feishu.cn/docx/DocToken",
)


def test_root_text_path_does_not_collide_with_first_child():
    xml = '<p block-id="blk">可能<b>说明</b>结尾</p>'
    snapshot = project_xml(xml, REF, 1)
    root_spans = [
        span
        for span in snapshot.source_map
        if span.writable and snapshot.projection[span.projection_start:span.projection_end] == "可能"
    ]
    assert len(root_spans) == 1
    assert root_spans[0].node_path == ()
    block = find_block(parse_blocks(snapshot.xml), "blk")
    node, is_tail = resolve_text_target(block, root_spans[0].node_path)
    assert is_tail is False
    assert node is block
    assert (node.text or "").startswith("可能")


def test_duplicate_source_is_report_only():
    xml = (
        '<p block-id="blkA">可能含糊。</p>'
        '<p block-id="blkB">可能含糊。</p>'
    )
    snapshot = project_xml(xml, REF, 1)
    start = snapshot.projection.index("可能含糊。")
    findings = [
        {
            "rule": "H002",
            "text": "可能含糊。",
            "line": 1,
            "column": start + 1,
        }
    ]
    bound = bind_findings(snapshot, findings)
    assert bound[0].location.writable is False
    assert bound[0].location.reason == "duplicate_source"


def test_nested_heading_binds_to_deepest_section():
    xml = (
        '<h1 block-id="h1">一级</h1>'
        '<h2 block-id="h2">二级</h2>'
        '<p block-id="p1">子节正文可能含糊。</p>'
    )
    root = parse_blocks(xml)
    sections = build_sections(root)
    snapshot = project_xml(xml, REF, 1)
    assert snapshot.sections == sections
    start = snapshot.projection.index("可能含糊")
    # Use a unique substring so duplicate_source does not fire.
    findings = [
        {
            "rule": "H002",
            "text": "可能含糊",
            "line": snapshot.projection[:start].count("\n") + 1,
            "column": start - snapshot.projection.rfind("\n", 0, start),
        }
    ]
    bound = bind_findings(snapshot, findings)
    assert bound[0].location.writable is True
    assert bound[0].section is not None
    assert bound[0].section.title == "二级"


def test_expected_fingerprints_must_match_block_groups():
    xml = (
        '<h1 block-id="blkTitle">标题</h1>'
        '<p block-id="blkParagraph">普通正文可能含糊。</p>'
    )
    snapshot = project_xml(xml, REF, 4)
    plan = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator=snapshot.sections[0].locator,
        initial_fingerprint=snapshot.sections[0].fingerprint,
        base_revision=4,
        approved_patch_ids=("p1",),
        expected_fingerprints=(),
        patches=(
            Patch(
                patch_id="p1",
                section_locator=snapshot.sections[0].locator,
                section_fingerprint=snapshot.sections[0].fingerprint,
                block_id="blkParagraph",
                node_path=(),
                source_start=0,
                source_end=9,
                before="普通正文可能含糊。",
                after="普通正文已经明确。",
                rule_id="H002",
                rationale="clarify",
            ),
        ),
    )
    with pytest.raises(PatchValidationError) as exc:
        validate_patches(snapshot, plan)
    assert exc.value.kind == "expected_fingerprints_mismatch"


def test_remap_rejects_ambiguous_duplicate_text_without_fuzzy_search():
    xml = (
        '<h1 block-id="t">标题</h1>'
        '<p block-id="a">可能含糊。</p>'
        '<p block-id="b">可能含糊。</p>'
    )
    snapshot = project_xml(xml, REF, 1)
    from wenlint.feishu import patches as patches_mod

    with pytest.raises(PatchValidationError) as exc:
        patches_mod._remap_patches(
            snapshot,
            [
                Patch(
                    patch_id="p1",
                    section_locator=snapshot.sections[0].locator,
                    section_fingerprint=snapshot.sections[0].fingerprint,
                    block_id="a",
                    node_path=(),
                    source_start=0,
                    source_end=5,
                    before="可能含糊。",
                    after="已经明确。",
                    rule_id="H002",
                    rationale="x",
                )
            ],
            snapshot.sections[0].locator,
        )
    assert exc.value.kind == "remap_failed"


def test_post_write_fetch_failure_is_partial_failure(monkeypatch):
    xml = '<h1 block-id="t">标题</h1><p block-id="a">第一块可能含糊。</p>'
    snapshot = project_xml(xml, REF, 10)
    section = snapshot.sections[0]
    before = "第一块可能含糊。"
    after = before.replace("可能", "已经")
    from wenlint.feishu.projection import replace_node_text, element_to_xml

    patched = replace_node_text(
        snapshot,
        Patch(
            patch_id="p1",
            section_locator=section.locator,
            section_fingerprint=section.fingerprint,
            block_id="a",
            node_path=(),
            source_start=0,
            source_end=len(before),
            before=before,
            after=after,
            rule_id="H002",
            rationale="x",
        ),
    )
    original = element_to_xml(find_block(parse_blocks(xml), "a"))
    expected_xml = xml.replace(original, patched, 1)
    expected_fp = project_xml(expected_xml, REF, 11).sections[0].fingerprint
    plan = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator=section.locator,
        initial_fingerprint=section.fingerprint,
        base_revision=10,
        approved_patch_ids=("p1",),
        expected_fingerprints=(expected_fp,),
        patches=(
            Patch(
                patch_id="p1",
                section_locator=section.locator,
                section_fingerprint=section.fingerprint,
                block_id="a",
                node_path=(),
                source_start=0,
                source_end=len(before),
                before=before,
                after=after,
                rule_id="H002",
                rationale="x",
            ),
        ),
    )

    class Client:
        def __init__(self):
            self.fetches = 0
            self.xml = xml
            self.revision = 10

        def fetch(self, ref):
            self.fetches += 1
            if self.revision > 10:
                from wenlint.feishu.lark import LarkCliError

                raise LarkCliError("network", "post-write fetch failed", retryable=True)
            return {
                "ok": True,
                "data": {
                    "document": {
                        "document_id": "DocToken",
                        "revision_id": self.revision,
                        "url": REF.canonical_url,
                    },
                    "content": self.xml,
                },
            }

        def replace_block(self, ref, block_id, block_xml, revision_id):
            self.xml = self.xml.replace(
                element_to_xml(find_block(parse_blocks(self.xml), block_id)),
                block_xml,
                1,
            )
            self.revision += 1
            return {"ok": True, "data": {"result": "success", "warnings": ["note"]}}

    import wenlint.feishu.patches as patches_mod

    monkeypatch.setattr(
        patches_mod,
        "inspect_document",
        lambda *args, **kwargs: InspectionReport(
            ok=True,
            source={
                "kind": "feishu",
                "document_id": "DocToken",
                "revision_id": 11,
                "url": REF.canonical_url,
                "identity": "user",
            },
            sections=(),
            findings=(),
        ),
    )
    result = apply_approved_section(Client(), REF, plan)
    assert result.status == "partial_failure"
    assert result.applied_patch_ids == ("p1",)
    assert result.details["kind"] == "network"


def test_approval_binding_documented():
    text = open("references/feishu.md", encoding="utf-8").read()
    assert "document_id" in text
    assert "expected_fingerprints" in text
    assert "任务重启" in text
