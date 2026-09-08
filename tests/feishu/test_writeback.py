"""State-machine tests for approved Feishu section writeback."""
from __future__ import annotations

import dataclasses
import re
from typing import Any

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.models import ApprovedSectionPlan, FetchedDocument, InspectionReport, Patch, UpdateReceipt
from wenlint.feishu.patches import apply_approved_section
from wenlint.feishu.projection import (
    element_to_xml,
    find_block,
    parse_blocks,
    project_xml,
    replace_node_text,
)

REF = dataclasses.replace(
    parse_document_ref("https://acme.feishu.cn/docx/DocToken"),
    document_id="DocToken",
    canonical_url="https://acme.feishu.cn/docx/DocToken",
)

XML_R10 = (
    '<h1 block-id="blkTitle">标题</h1>'
    '<p block-id="blkA">第一块可能含糊。</p>'
    '<p block-id="blkB">第二块或许含糊。</p>'
)


def _plan_for(xml: str, revision: int = 10) -> ApprovedSectionPlan:
    snapshot = project_xml(xml, REF, revision)
    section = snapshot.sections[0]
    patches: list[Patch] = []
    for block_id, hedge, after in (
        ("blkA", "可能", "已经"),
        ("blkB", "或许", "确定"),
    ):
        if block_id not in section.block_ids:
            continue
        root = parse_blocks(snapshot.xml)
        block = find_block(root, block_id)
        text = block.text or ""
        start = text.index(hedge)
        patches.append(
            Patch(
                patch_id="p1" if block_id == "blkA" else "p2",
                section_locator=section.locator,
                section_fingerprint=section.fingerprint,
                block_id=block_id,
                node_path=(),
                source_start=start,
                source_end=start + len(hedge),
                before=hedge,
                after=after,
                rule_id="H002",
                rationale="clarify",
            )
        )

    expected: list[str] = []
    working = xml
    for patch in patches:
        snap = project_xml(working, REF, revision)
        patched_block = replace_node_text(snap, patch)
        root = parse_blocks(working)
        original = element_to_xml(find_block(root, patch.block_id))
        working = working.replace(original, patched_block, 1)
        expected.append(project_xml(working, REF, revision).sections[0].fingerprint)

    return ApprovedSectionPlan(
        document_id="DocToken",
        section_locator=section.locator,
        initial_fingerprint=section.fingerprint,
        base_revision=revision,
        approved_patch_ids=tuple(p.patch_id for p in patches),
        expected_fingerprints=tuple(expected),
        patches=tuple(patches),
    )


class ScriptedClient:
    def __init__(self, xml: str = XML_R10) -> None:
        self.events: list[str] = []
        self.replace_attempts = 0
        self._revision = 10
        self._xml = xml
        self._conflict_once = False
        self._conflict_used = False

    def conflict_once_with_unchanged_target_section(self) -> None:
        self._conflict_once = True

    def fetch(self, ref):
        self.events.append(f"fetch:r{self._revision}")
        return FetchedDocument(
            ref=REF,
            revision_id=self._revision,
            xml=self._xml,
        )

    def replace_block(self, ref, block_id, xml, revision_id):
        self.replace_attempts += 1
        self.events.append(f"replace:{block_id}:r{revision_id}")
        from wenlint.feishu.lark import LarkCliError

        if self._conflict_once and not self._conflict_used:
            self._conflict_used = True
            self._revision += 1
            raise LarkCliError(
                "revision_conflict",
                "revision conflict",
                retryable=True,
                details={"result": "conflict"},
            )
        if revision_id != self._revision:
            raise LarkCliError(
                "revision_conflict",
                "revision conflict",
                retryable=True,
            )

        root = parse_blocks(self._xml)
        original = element_to_xml(find_block(root, block_id))
        self._xml = self._xml.replace(original, xml, 1)
        self._xml = re.sub(
            r'block-id="([^"]+)"',
            lambda match: (
                match.group(0)
                if match.group(1).endswith("-new")
                else f'block-id="{match.group(1)}-new"'
            ),
            self._xml,
        )
        self._revision += 1
        # Intentionally report a stale revision to prove apply ignores receipts.
        return UpdateReceipt(
            result="success",
            reported_revision_id=1,
            warnings=(),
        )


def test_refetches_after_every_block_and_uses_new_revision(monkeypatch):
    plan = _plan_for(XML_R10)
    client = ScriptedClient()

    import wenlint.feishu.patches as patches_mod

    def _fake_inspect(client_obj, ref, profile="general"):
        client_obj.events.append(f"final-inspect:r{client_obj._revision}")
        return InspectionReport(
            ok=True,
            source={
                "kind": "feishu",
                "document_id": "DocToken",
                "revision_id": client_obj._revision,
                "url": REF.canonical_url,
                "identity": "user",
            },
            sections=(),
            findings=(),
        )

    monkeypatch.setattr(patches_mod, "inspect_document", _fake_inspect)
    result = apply_approved_section(client, REF, plan)
    assert result.status == "success"
    assert client.events == [
        "fetch:r10",
        "replace:blkA:r10",
        "fetch:r11",
        "replace:blkB-new:r11",
        "fetch:r12",
        "final-inspect:r12",
    ]


def test_other_section_change_can_retry_revision_conflict(monkeypatch):
    xml = '<h1 block-id="blkTitle">标题</h1><p block-id="blkA">第一块可能含糊。</p>'
    plan = _plan_for(xml)
    client = ScriptedClient(xml)
    client.conflict_once_with_unchanged_target_section()

    import wenlint.feishu.patches as patches_mod

    monkeypatch.setattr(
        patches_mod,
        "inspect_document",
        lambda *args, **kwargs: InspectionReport(
            ok=True,
            source={
                "kind": "feishu",
                "document_id": "DocToken",
                "revision_id": client._revision,
                "url": REF.canonical_url,
                "identity": "user",
            },
            sections=(),
            findings=(),
        ),
    )
    result = apply_approved_section(client, REF, plan)
    assert result.status == "success"
    assert client.replace_attempts == 2
