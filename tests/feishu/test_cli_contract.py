"""End-to-end ``wenlint-feishu`` CLI contract tests with a fake ``lark-cli``."""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.models import Patch
from wenlint.feishu.projection import (
    element_to_xml,
    find_block,
    parse_blocks,
    project_xml,
    replace_node_text,
)

ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).resolve().parent / "fake_lark_cli.py"
DOC_URL = "https://acme.feishu.cn/docx/DocToken"
WIKI_URL = "https://acme.feishu.cn/wiki/WikiToken"


def _run(args: list[str], *, env: dict[str, str], cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, "-m", "wenlint.feishu.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or ROOT),
        env=env,
        shell=False,
    )


def _base_env(tmp_path: Path, mode: str = "success") -> dict[str, str]:
    env = os.environ.copy()
    env["WENLINT_LARK_CLI"] = str(FAKE)
    env["FAKE_LARK_MODE"] = mode
    env["FAKE_LARK_RECORD"] = str(tmp_path / "argv.json")
    return env


def test_inspect_success_json(tmp_path):
    env = _base_env(tmp_path)
    result = _run([DOC_URL, "--json"], env=env)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["source"]["identity"] == "user"
    assert "findings" in payload


def test_wiki_resolution(tmp_path):
    env = _base_env(tmp_path)
    result = _run(["inspect", WIKI_URL, "--json"], env=env)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["source"]["document_id"] == "DocToken"


def test_missing_auth_exit_3(tmp_path):
    env = _base_env(tmp_path, mode="auth")
    result = _run([DOC_URL, "--json"], env=env)
    assert result.returncode == 3
    err = json.loads(result.stderr)
    assert err["kind"] == "auth"
    assert "content" not in err


def test_stdout_stderr_privacy_on_errors(tmp_path):
    env = _base_env(tmp_path, mode="scope")
    result = _run([DOC_URL, "--json"], env=env)
    assert result.returncode == 3
    assert "<p" not in result.stdout
    assert "<p" not in result.stderr
    err = json.loads(result.stderr)
    assert err["missing_scopes"] == ["docs:read"]


def test_invalid_url_exit_2(tmp_path):
    env = _base_env(tmp_path)
    result = _run(["not-a-url", "--json"], env=env)
    assert result.returncode == 2


def test_apply_success_with_stateful_fake(tmp_path):
    xml = (
        '<h1 block-id="blkTitle">产品设计</h1>'
        '<p block-id="blkParagraph">普通正文可能含糊。</p>'
    )
    ref = dataclasses.replace(
        parse_document_ref(DOC_URL),
        document_id="DocToken",
        canonical_url=DOC_URL,
    )
    snapshot = project_xml(xml, ref, 12)
    section = snapshot.sections[0]
    before = "普通正文可能含糊。"
    after = "普通正文已经明确。"
    patch = Patch(
        patch_id="p1",
        section_locator=section.locator,
        section_fingerprint=section.fingerprint,
        block_id="blkParagraph",
        node_path=(),
        source_start=0,
        source_end=len(before),
        before=before,
        after=after,
        rule_id="H002",
        rationale="clarify",
    )
    patched = replace_node_text(snapshot, patch)
    original = element_to_xml(find_block(parse_blocks(snapshot.xml), "blkParagraph"))
    new_xml = snapshot.xml.replace(original, patched, 1)
    expected_fp = project_xml(new_xml, ref, 12).sections[0].fingerprint

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "document_id": "DocToken",
                "revision_id": 12,
                "url": DOC_URL,
                "content": xml,
                "block_xml": {"blkParagraph": original},
            }
        ),
        encoding="utf-8",
    )

    manifest = {
        "document_id": "DocToken",
        "section_locator": section.locator,
        "initial_fingerprint": section.fingerprint,
        "base_revision": 12,
        "approved_patch_ids": ["p1"],
        "expected_fingerprints": [expected_fp],
        "patches": [
            {
                "patch_id": "p1",
                "section_locator": section.locator,
                "section_fingerprint": section.fingerprint,
                "block_id": "blkParagraph",
                "node_path": [],
                "source_start": 0,
                "source_end": len(before),
                "before": before,
                "after": after,
                "rule_id": "H002",
                "rationale": "clarify",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    env = _base_env(tmp_path)
    env["FAKE_LARK_STATE"] = str(state_path)
    result = _run(
        ["apply", DOC_URL, "--patch-file", str(path.name), "--json"],
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "success"
    assert payload["applied_patch_ids"] == ["p1"]
    assert before not in result.stdout
    assert after not in result.stdout


def test_apply_conflict_before_write_exit_4(tmp_path):
    xml = (
        '<h1 block-id="blkTitle">产品设计</h1>'
        '<p block-id="blkParagraph">普通正文可能含糊。</p>'
    )
    ref = dataclasses.replace(
        parse_document_ref(DOC_URL),
        document_id="DocToken",
        canonical_url=DOC_URL,
    )
    snapshot = project_xml(xml, ref, 12)
    section = snapshot.sections[0]
    manifest = {
        "document_id": "DocToken",
        "section_locator": section.locator,
        "initial_fingerprint": "sha256:stale",
        "base_revision": 12,
        "approved_patch_ids": ["p1"],
        "expected_fingerprints": ["sha256:x"],
        "patches": [
            {
                "patch_id": "p1",
                "section_locator": section.locator,
                "section_fingerprint": "sha256:stale",
                "block_id": "blkParagraph",
                "node_path": [],
                "source_start": 0,
                "source_end": 9,
                "before": "普通正文可能含糊。",
                "after": "普通正文已经明确。",
                "rule_id": "H002",
                "rationale": "clarify",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "document_id": "DocToken",
                "revision_id": 12,
                "url": DOC_URL,
                "content": xml,
            }
        ),
        encoding="utf-8",
    )
    env = _base_env(tmp_path)
    env["FAKE_LARK_STATE"] = str(state_path)
    result = _run(
        ["apply", DOC_URL, "--patch-file", path.name, "--json"],
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["status"] == "conflict"
