"""Direct regressions for independent acceptance gaps after abf7c80."""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wenlint.feishu.document import DocumentRefError, parse_document_ref, resolve_fetched_docx_ref
from wenlint.feishu.lark import LarkCliError, LarkClient
from wenlint.feishu.models import ApprovedSectionPlan, InspectionReport, Patch
from wenlint.feishu.patches import (
    ManifestError,
    PatchValidationError,
    apply_approved_section,
    load_manifest,
    validate_patches,
)
from wenlint.feishu.projection import (
    element_to_xml,
    find_block,
    parse_blocks,
    project_xml,
    replace_node_text,
)
from wenlint.feishu.sections import locate_section

REF = dataclasses.replace(
    parse_document_ref("https://acme.feishu.cn/docx/DocToken"),
    document_id="DocToken",
    canonical_url="https://acme.feishu.cn/docx/DocToken",
)
ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).resolve().parent / "fake_lark_cli.py"
DOC_URL = "https://acme.feishu.cn/docx/DocToken"


def test_nested_duplicate_titles_reset_ordinals_under_each_parent():
    xml = (
        '<h1 block-id="a">同名</h1>'
        '<h2 block-id="a1">子节</h2>'
        '<p block-id="a1b">甲。</p>'
        '<h1 block-id="b">同名</h1>'
        '<h2 block-id="b1">子节</h2>'
        '<p block-id="b1b">乙。</p>'
    )
    snapshot = project_xml(xml, REF, 1)
    locators = [section.locator for section in snapshot.sections]
    assert "同名[1]/子节[1]" in locators
    assert "同名[2]/子节[1]" in locators
    assert "同名[2]/子节[2]" not in locators
    second = locate_section(snapshot, "同名[2]/子节[1]")
    assert second.block_ids[0] == "b1"


def test_fingerprint_tracks_resource_id_and_semantic_attrs_not_block_id():
    base = '<h1 block-id="t">标题</h1><p block-id="b">正文。<cite id="resA">注</cite></p>'
    renamed = '<h1 block-id="t2">标题</h1><p block-id="b2">正文。<cite id="resA">注</cite></p>'
    resource = '<h1 block-id="t">标题</h1><p block-id="b">正文。<cite id="resB">注</cite></p>'
    semantic = '<h1 block-id="t">标题</h1><p block-id="b" lang="zh">正文。<cite id="resA">注</cite></p>'
    nested = '<h1 block-id="t">标题</h1><p block-id="b">正文。<span><cite id="resA">注</cite></span></p>'
    base_fp = project_xml(base, REF, 1).sections[0].fingerprint
    assert project_xml(renamed, REF, 2).sections[0].fingerprint == base_fp
    assert project_xml(resource, REF, 3).sections[0].fingerprint != base_fp
    assert project_xml(semantic, REF, 4).sections[0].fingerprint != base_fp
    assert project_xml(nested, REF, 5).sections[0].fingerprint != base_fp


def test_resolve_fetched_docx_ref_rejects_wiki_and_mismatched_tokens():
    input_ref = parse_document_ref("https://acme.feishu.cn/wiki/WikiToken")
    ok = resolve_fetched_docx_ref(
        input_ref, "DocToken", "https://acme.feishu.cn/docx/DocToken?from=x"
    )
    assert ok.document_id == "DocToken"
    assert ok.canonical_url == "https://acme.feishu.cn/docx/DocToken"
    with pytest.raises(DocumentRefError):
        resolve_fetched_docx_ref(
            input_ref, "DocToken", "https://acme.feishu.cn/wiki/WikiToken"
        )
    with pytest.raises(DocumentRefError):
        resolve_fetched_docx_ref(
            input_ref, "DocToken", "https://acme.feishu.cn/docx/OtherToken"
        )
    with pytest.raises(DocumentRefError):
        resolve_fetched_docx_ref(input_ref, "DocToken", "http://acme.feishu.cn/docx/DocToken")


def test_manifest_requires_base_revision_and_patch_fingerprint_binding(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    snapshot = project_xml(
        '<h1 block-id="t">标题</h1><p block-id="p">普通正文可能含糊。</p>',
        REF,
        4,
    )
    section = snapshot.sections[0]
    good_patch = {
        "patch_id": "p1",
        "section_locator": section.locator,
        "section_fingerprint": section.fingerprint,
        "block_id": "p",
        "node_path": [],
        "source_start": 0,
        "source_end": 9,
        "before": "普通正文可能含糊。",
        "after": "普通正文已经明确。",
        "rule_id": "H002",
        "rationale": "x",
    }
    missing = {
        "document_id": "DocToken",
        "section_locator": section.locator,
        "initial_fingerprint": section.fingerprint,
        "approved_patch_ids": ["p1"],
        "expected_fingerprints": ["sha256:x"],
        "patches": [good_patch],
    }
    path = tmp_path / "m.json"
    path.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(ManifestError) as exc:
        load_manifest(path, REF)
    assert exc.value.kind == "manifest_schema"

    bad_fp = dict(good_patch)
    bad_fp["section_fingerprint"] = "sha256:other"
    plan = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator=section.locator,
        initial_fingerprint=section.fingerprint,
        base_revision=4,
        approved_patch_ids=("p1",),
        expected_fingerprints=("sha256:x",),
        patches=(
            Patch(
                patch_id="p1",
                section_locator=section.locator,
                section_fingerprint="sha256:other",
                block_id="p",
                node_path=(),
                source_start=0,
                source_end=9,
                before="普通正文可能含糊。",
                after="普通正文已经明确。",
                rule_id="H002",
                rationale="x",
            ),
        ),
    )
    with pytest.raises(PatchValidationError) as exc2:
        validate_patches(snapshot, plan)
    assert exc2.value.kind == "fingerprint_mismatch"

    dup = {
        "document_id": "DocToken",
        "section_locator": section.locator,
        "initial_fingerprint": section.fingerprint,
        "base_revision": 4,
        "approved_patch_ids": ["p1", "p1"],
        "expected_fingerprints": ["sha256:x"],
        "patches": [good_patch],
    }
    path.write_text(json.dumps(dup), encoding="utf-8")
    with pytest.raises(ManifestError) as exc3:
        load_manifest(path, REF)
    assert exc3.value.kind in {"duplicate_approved_id", "manifest_schema", "missing_patch"}


def test_preflight_lark_error_is_not_document_conflict(monkeypatch):
    plan = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator="标题[1]",
        initial_fingerprint="sha256:x",
        base_revision=10,
        approved_patch_ids=("p1",),
        expected_fingerprints=("sha256:y",),
        patches=(
            Patch(
                patch_id="p1",
                section_locator="标题[1]",
                section_fingerprint="sha256:x",
                block_id="a",
                node_path=(),
                source_start=0,
                source_end=1,
                before="a",
                after="b",
                rule_id="H002",
                rationale="x",
            ),
        ),
    )

    class Client:
        def fetch(self, ref):
            raise LarkCliError("network", "fetch failed", retryable=True)

        def replace_block(self, *args, **kwargs):
            raise AssertionError("no writes on dependency failure")

    with pytest.raises(LarkCliError) as exc:
        apply_approved_section(Client(), REF, plan)
    assert exc.value.kind == "network"


def test_second_retry_preserves_non_conflict_error_kind(monkeypatch):
    xml = '<h1 block-id="t">标题</h1><p block-id="a">第一块可能含糊。</p>'
    snapshot = project_xml(xml, REF, 10)
    section = snapshot.sections[0]
    before = "可能"
    after = "已经"
    patched = replace_node_text(
        snapshot,
        Patch(
            patch_id="p1",
            section_locator=section.locator,
            section_fingerprint=section.fingerprint,
            block_id="a",
            node_path=(),
            source_start=3,
            source_end=5,
            before=before,
            after=after,
            rule_id="H002",
            rationale="x",
        ),
    )
    original = element_to_xml(find_block(parse_blocks(xml), "a"))
    expected_fp = project_xml(xml.replace(original, patched, 1), REF, 11).sections[0].fingerprint
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
                source_start=3,
                source_end=5,
                before=before,
                after=after,
                rule_id="H002",
                rationale="x",
            ),
        ),
    )

    class Client:
        def __init__(self):
            self.attempts = 0
            self.revision = 10
            self.xml = xml

        def fetch(self, ref):
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
            self.attempts += 1
            if self.attempts == 1:
                self.revision += 1
                raise LarkCliError("revision_conflict", "first", retryable=True)
            raise LarkCliError("network", "second replace network", retryable=True)

    result = apply_approved_section(Client(), REF, plan)
    assert result.status == "conflict"
    assert result.details["kind"] == "network"
    assert result.applied_patch_ids == ()


def test_merge_block_patches_uses_tree_not_document_string_replace():
    xml = (
        '<h1 block-id="t">标题</h1>'
        '<p block-id="a">前缀可能中间可能结尾。</p>'
        '<p block-id="b">前缀可能中间可能结尾。</p>'
    )
    snapshot = project_xml(xml, REF, 1)
    section = snapshot.sections[0]
    patches = [
        Patch(
            patch_id="p1",
            section_locator=section.locator,
            section_fingerprint=section.fingerprint,
            block_id="a",
            node_path=(),
            source_start=2,
            source_end=4,
            before="可能",
            after="已经",
            rule_id="H002",
            rationale="first",
        ),
        Patch(
            patch_id="p2",
            section_locator=section.locator,
            section_fingerprint=section.fingerprint,
            block_id="a",
            node_path=(),
            source_start=6,
            source_end=8,
            before="可能",
            after="已经",
            rule_id="H002",
            rationale="second",
        ),
    ]
    from wenlint.feishu import patches as patches_mod
    import inspect

    source = inspect.getsource(patches_mod._merge_block_patches)
    assert ".xml.replace(" not in source
    merged = patches_mod._merge_block_patches(snapshot, "a", patches)
    assert "前缀已经中间已经结尾。" in merged
    sibling = element_to_xml(find_block(parse_blocks(snapshot.xml), "b"))
    assert "可能" in sibling
    assert "已经" not in sibling


def test_probe_fails_when_update_help_omits_block_id(tmp_path, monkeypatch):
    script = tmp_path / "partial_lark.py"
    script.write_text(
        "\n".join(
            [
                "import sys",
                "args = sys.argv[1:]",
                "if args == ['--version']:",
                "    print('partial 1.0')",
                "elif args[:2] == ['docs', '+fetch'] and '--help' in args:",
                "    print('docs +fetch --doc --doc-format xml --detail full --as user --format json wiki')",
                "elif args[:2] == ['docs', '+update'] and '--help' in args:",
                "    print('docs +update block_replace --revision-id --as user --format json')",
                "else:",
                "    raise SystemExit(1)",
            ]
        ),
        encoding="utf-8",
    )
    client = LarkClient(executable=[sys.executable, str(script)])
    with pytest.raises(LarkCliError) as exc:
        client.probe()
    assert exc.value.kind == "incompatible_cli"
    missing = exc.value.details["missing_capabilities"]
    assert any("block-id" in item for item in missing)


def test_apply_network_during_preflight_exits_3(tmp_path):
    xml = '<h1 block-id="t">标题</h1><p block-id="p">普通正文可能含糊。</p>'
    snapshot = project_xml(xml, REF, 12)
    section = snapshot.sections[0]
    manifest = {
        "document_id": "DocToken",
        "section_locator": section.locator,
        "initial_fingerprint": section.fingerprint,
        "base_revision": 12,
        "approved_patch_ids": ["p1"],
        "expected_fingerprints": ["sha256:x"],
        "patches": [
            {
                "patch_id": "p1",
                "section_locator": section.locator,
                "section_fingerprint": section.fingerprint,
                "block_id": "p",
                "node_path": [],
                "source_start": 0,
                "source_end": 9,
                "before": "普通正文可能含糊。",
                "after": "普通正文已经明确。",
                "rule_id": "H002",
                "rationale": "x",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "document_id": "DocToken",
                "revision_id": 12,
                "url": DOC_URL,
                "content": xml,
                "fail_fetch_after": 0,
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
        [
            sys.executable,
            "-m",
            "wenlint.feishu.cli",
            "apply",
            DOC_URL,
            "--patch-file",
            path.name,
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        shell=False,
    )
    assert result.returncode == 3, result.stderr
    err = json.loads(result.stderr)
    assert err["kind"] == "network"
    assert result.stdout == "" or "success" not in result.stdout


def test_skill_recovery_commands_are_explicit():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "pipx install wenlint" in text or "pip install wenlint" in text
    assert "lark-cli" in text and ("auth login" in text or "授权" in text)
    assert "禁止" in text and ("静默" in text or "自动安装" in text)
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "36 个回归测试" not in readme
