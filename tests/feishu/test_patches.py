"""Tests for approved patch manifest loading and validation."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.models import ApprovedSectionPlan, Patch
from wenlint.feishu.patches import ManifestError, PatchValidationError, load_manifest, validate_patches
from wenlint.feishu.projection import project_xml

REF = dataclasses.replace(
    parse_document_ref("https://acme.feishu.cn/docx/DocToken"),
    document_id="DocToken",
    canonical_url="https://acme.feishu.cn/docx/DocToken",
)

SIMPLE_XML = (
    '<h1 block-id="blkTitle">标题</h1>'
    '<p block-id="blkParagraph">普通正文可能含糊。</p>'
)


@pytest.fixture
def snapshot():
    return project_xml(SIMPLE_XML, REF, 4)


def _manifest_dict(**overrides):
    payload = {
        "document_id": "DocToken",
        "section_locator": "标题[1]",
        "initial_fingerprint": "sha256:placeholder",
        "approved_patch_ids": ["p1"],
        "expected_fingerprints": ["sha256:after"],
        "patches": [
            {
                "patch_id": "p1",
                "section_locator": "标题[1]",
                "section_fingerprint": "sha256:placeholder",
                "block_id": "blkParagraph",
                "node_path": [],
                "source_start": 0,
                "source_end": 9,
                "before": "普通正文可能含糊。",
                "after": "普通正文已经明确。",
                "rule_id": "H002",
                "rationale": "clarify hedge",
            }
        ],
    }
    payload.update(overrides)
    return payload


def write_manifest(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(_manifest_dict(**overrides), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_manifest_must_match_document_and_section(tmp_path, monkeypatch):
    path = write_manifest(tmp_path, document_id="another-doc")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ManifestError) as exc:
        load_manifest(path, REF)
    assert exc.value.kind == "document_mismatch"


def test_manifest_rejects_path_outside_cwd(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    path = write_manifest(outside)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    with pytest.raises(ManifestError) as exc:
        load_manifest(path, REF)
    assert exc.value.kind == "manifest_path"


def test_overlapping_patches_are_rejected(snapshot):
    plan = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator="标题[1]",
        initial_fingerprint=snapshot.sections[0].fingerprint,
        approved_patch_ids=("p1", "p2"),
        expected_fingerprints=("a",),
        patches=(
            Patch(
                patch_id="p1",
                section_locator="标题[1]",
                section_fingerprint=snapshot.sections[0].fingerprint,
                block_id="blkParagraph",
                node_path=(),
                source_start=2,
                source_end=5,
                before="正文可",
                after="正文已",
                rule_id="H002",
                rationale="x",
            ),
            Patch(
                patch_id="p2",
                section_locator="标题[1]",
                section_fingerprint=snapshot.sections[0].fingerprint,
                block_id="blkParagraph",
                node_path=(),
                source_start=4,
                source_end=7,
                before="可能含",
                after="已经明",
                rule_id="H002",
                rationale="y",
            ),
        ),
    )
    with pytest.raises(PatchValidationError) as exc:
        validate_patches(snapshot, plan)
    assert exc.value.kind == "overlapping_patches"


def test_empty_or_equal_before_after_rejected(snapshot):
    plan = ApprovedSectionPlan(
        document_id="DocToken",
        section_locator="标题[1]",
        initial_fingerprint=snapshot.sections[0].fingerprint,
        approved_patch_ids=("p1",),
        expected_fingerprints=("a",),
        patches=(
            Patch(
                patch_id="p1",
                section_locator="标题[1]",
                section_fingerprint=snapshot.sections[0].fingerprint,
                block_id="blkParagraph",
                node_path=(),
                source_start=0,
                source_end=9,
                before="普通正文可能含糊。",
                after="普通正文可能含糊。",
                rule_id="H002",
                rationale="noop",
            ),
        ),
    )
    with pytest.raises(PatchValidationError) as exc:
        validate_patches(snapshot, plan)
    assert exc.value.kind == "noop_patch"
