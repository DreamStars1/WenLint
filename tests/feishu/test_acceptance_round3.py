"""Direct regressions for independent acceptance gaps after 639f9b4."""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wenlint.feishu.document import DocumentRefError, parse_document_ref
from wenlint.feishu.findings import bind_findings
from wenlint.feishu.models import ApprovedSectionPlan, FetchedDocument, Patch, UpdateReceipt
from wenlint.feishu.patches import PatchValidationError, validate_patches
from wenlint.feishu.projection import project_xml
from wenlint.scanner import scan_text

REF = dataclasses.replace(
    parse_document_ref("https://acme.feishu.cn/docx/DocToken"),
    document_id="DocToken",
    canonical_url="https://acme.feishu.cn/docx/DocToken",
)
ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).resolve().parent / "fake_lark_cli.py"
DOC_URL = "https://acme.feishu.cn/docx/DocToken"


def _public_findings(projection: str) -> list[dict]:
    return [
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
            "sentence": item["sentence"],
            "before": None,
            "after": None,
        }
        for item in scan_text(projection)
    ]


def test_inspect_json_includes_source_offsets_for_exact_findings(tmp_path):
    env = os.environ.copy()
    env["WENLINT_LARK_CLI"] = str(FAKE)
    env["FAKE_LARK_MODE"] = "success"
    env["FAKE_LARK_RECORD"] = str(tmp_path / "argv.json")
    result = subprocess.run(
        [sys.executable, "-m", "wenlint.feishu.cli", DOC_URL, "--json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
        shell=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    finding = next(item for item in payload["findings"] if item.get("rule") == "H002")
    assert finding["location"]["source_start"] == 4
    assert finding["location"]["source_end"] == 6


def test_heading_and_cite_findings_are_not_writable():
    heading_xml = '<h1 block-id="h">标题可能含糊</h1><p block-id="p">正文。</p>'
    snapshot = project_xml(heading_xml, REF, 1)
    # Projection is "# 标题可能含糊\n正文。" — column 4 of line 1 is 标; "可能" starts at col 5.
    forced = [
        {
            "rule": "H002",
            "type": "candidate",
            "severity": "candidate",
            "category": "hedge",
            "message": "可能",
            "review_hint": "check",
            "line": 1,
            "column": 5,
            "text": "可能",
            "sentence": "# 标题可能含糊",
            "before": None,
            "after": None,
        }
    ]
    bound = bind_findings(snapshot, forced)
    assert bound[0].location.writable is False
    assert bound[0].location.reason == "unsupported_block"

    cite_xml = (
        '<h1 block-id="t">标题</h1>'
        '<p block-id="p">正文。<cite id="resA">可能</cite></p>'
    )
    cite_snap = project_xml(cite_xml, REF, 1)
    section = cite_snap.sections[0]
    heading_or_cite_patch_plan = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator=section.locator,
        initial_fingerprint=section.fingerprint,
        base_revision=1,
        approved_patch_ids=("p1",),
        expected_fingerprints=("sha256:x",),
        patches=(
            Patch(
                patch_id="p1",
                section_locator=section.locator,
                section_fingerprint=section.fingerprint,
                block_id="p",
                node_path=(0,),
                source_start=0,
                source_end=2,
                before="可能",
                after="已经",
                rule_id="H002",
                rationale="cite",
            ),
        ),
    )
    with pytest.raises(PatchValidationError) as exc:
        validate_patches(cite_snap, heading_or_cite_patch_plan)
    assert exc.value.kind == "unsupported_block"


def test_validate_patches_requires_bound_wenlint_finding():
    snapshot = project_xml(
        '<h1 block-id="t">标题</h1><p block-id="p">普通正文可能含糊。</p>',
        REF,
        1,
    )
    section = snapshot.sections[0]
    plan_with_rule_id_not_present_in_findings = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator=section.locator,
        initial_fingerprint=section.fingerprint,
        base_revision=1,
        approved_patch_ids=("p1",),
        expected_fingerprints=("sha256:x",),
        patches=(
            Patch(
                patch_id="p1",
                section_locator=section.locator,
                section_fingerprint=section.fingerprint,
                block_id="p",
                node_path=(),
                source_start=4,
                source_end=6,
                before="可能",
                after="已经",
                rule_id="RULE_NOT_IN_FINDINGS",
                rationale="x",
            ),
        ),
    )
    with pytest.raises(PatchValidationError) as exc:
        validate_patches(snapshot, plan_with_rule_id_not_present_in_findings)
    assert exc.value.kind == "finding_mismatch"


def test_expected_fingerprints_must_match_derived_values_before_write():
    snapshot = project_xml(
        '<h1 block-id="t">标题</h1><p block-id="p">普通正文可能含糊。</p>',
        REF,
        1,
    )
    section = snapshot.sections[0]
    plan_with_expected_fingerprints = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator=section.locator,
        initial_fingerprint=section.fingerprint,
        base_revision=1,
        approved_patch_ids=("p1",),
        expected_fingerprints=("sha256:not-the-derived-value",),
        patches=(
            Patch(
                patch_id="p1",
                section_locator=section.locator,
                section_fingerprint=section.fingerprint,
                block_id="p",
                node_path=(),
                source_start=4,
                source_end=6,
                before="可能",
                after="已经",
                rule_id="H002",
                rationale="x",
            ),
        ),
    )
    with pytest.raises(PatchValidationError) as exc:
        validate_patches(snapshot, plan_with_expected_fingerprints)
    assert exc.value.kind == "expected_fingerprint_mismatch"


def test_invalid_revision_id_exits_3_compact_json(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "document_id": "DocToken",
                "revision_id": "not-an-int",
                "url": DOC_URL,
                "content": (
                    '<h1 block-id="blkTitle">标题</h1>'
                    '<p block-id="blkParagraph">普通正文可能含糊。</p>'
                ),
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["WENLINT_LARK_CLI"] = str(FAKE)
    env["FAKE_LARK_MODE"] = "success"
    env["FAKE_LARK_STATE"] = str(state)
    env["FAKE_LARK_RECORD"] = str(tmp_path / "argv.json")
    result = subprocess.run(
        [sys.executable, "-m", "wenlint.feishu.cli", DOC_URL, "--json"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        shell=False,
    )
    assert result.returncode == 3
    assert json.loads(result.stderr)["kind"] == "invalid_response"
    assert result.stdout == ""


def test_remote_error_message_does_not_leak_document_xml(tmp_path):
    secret_xml = '<p block-id="secret">机密正文可能泄露。</p>'
    env = os.environ.copy()
    env["WENLINT_LARK_CLI"] = str(FAKE)
    env["FAKE_LARK_MODE"] = "leaky_error"
    env["FAKE_LARK_LEAK"] = secret_xml
    env["FAKE_LARK_RECORD"] = str(tmp_path / "argv.json")
    result = subprocess.run(
        [sys.executable, "-m", "wenlint.feishu.cli", DOC_URL, "--json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
        shell=False,
    )
    assert result.returncode == 3
    assert secret_xml not in result.stderr
    assert secret_xml not in result.stdout
    assert json.loads(result.stderr)["kind"] == "network"


def test_parse_document_ref_rejects_non_feishu_hosts():
    with pytest.raises(DocumentRefError):
        parse_document_ref("https://evil.example/docx/DocToken")


def test_top_level_warnings_are_surfaced_and_verified(monkeypatch):
    from wenlint.feishu.models import InspectionReport
    from wenlint.feishu.patches import apply_approved_section
    import wenlint.feishu.patches as patches_mod

    xml = '<h1 block-id="t">标题</h1><p block-id="a">第一块可能含糊。</p>'
    snapshot = project_xml(xml, REF, 10)
    section = snapshot.sections[0]
    patch = Patch(
        patch_id="p1",
        section_locator=section.locator,
        section_fingerprint=section.fingerprint,
        block_id="a",
        node_path=(),
        source_start=3,
        source_end=5,
        before="可能",
        after="已经",
        rule_id="H002",
        rationale="x",
    )
    from wenlint.feishu.projection import (
        element_to_xml,
        find_block,
        parse_blocks,
        replace_node_text,
    )

    patched = replace_node_text(snapshot, patch)
    original = element_to_xml(find_block(parse_blocks(xml), "a"))
    after_xml = xml.replace(original, patched, 1)
    expected_fp = project_xml(after_xml, REF, 10).sections[0].fingerprint
    plan = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator=section.locator,
        initial_fingerprint=section.fingerprint,
        base_revision=10,
        approved_patch_ids=("p1",),
        expected_fingerprints=(expected_fp,),
        patches=(patch,),
    )

    class Client:
        def __init__(self) -> None:
            self._revision = 10
            self._xml = xml

        def fetch(self, ref):
            return FetchedDocument(
                ref=REF,
                revision_id=self._revision,
                xml=self._xml,
            )

        def replace_block(self, ref, block_id, block_xml, revision_id):
            root = parse_blocks(self._xml)
            original_block = element_to_xml(find_block(root, block_id))
            self._xml = self._xml.replace(original_block, block_xml, 1)
            self._revision += 1
            return UpdateReceipt(
                result="success",
                reported_revision_id=self._revision,
                warnings=("server-side normalization warning",),
            )

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
    assert result.status == "success"
    assert result.details["warnings"] == ["server-side normalization warning"]
    assert result.details["verified_after_warnings"] is True


def test_skill_docs_describe_safe_revision_conflict_retry():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "revision 冲突且目标章节未变时，可重映射并重试一次" in text
    assert "冲突会使原章节批准失效" not in text


def test_readme_reflects_feishu_delivery():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "36 tests" not in readme
    assert "wenlint/feishu/" in readme
    assert "v0.1 定案" not in readme
