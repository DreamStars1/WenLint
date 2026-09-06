"""Contract tests for the bounded non-shell ``lark-cli`` adapter."""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.lark import LarkCliError, LarkClient

DOC_URL = "https://acme.feishu.cn/docx/DocToken"
FAKE_SCRIPT = Path(__file__).resolve().parent / "fake_lark_cli.py"
RESOLVED_REF = dataclasses.replace(
    parse_document_ref(DOC_URL),
    document_id="DocToken",
    canonical_url=DOC_URL,
)


@pytest.fixture
def fake_lark(tmp_path, monkeypatch):
    record = tmp_path / "argv.json"

    class Recorder:
        def __init__(self) -> None:
            self.executable = str(FAKE_SCRIPT)
            self.record = record

        @property
        def last_argv(self) -> list[str]:
            return json.loads(self.record.read_text(encoding="utf-8"))

    monkeypatch.setenv("FAKE_LARK_MODE", "success")
    monkeypatch.setenv("FAKE_LARK_RECORD", str(record))
    return Recorder()


def _client(fake_lark, **kwargs) -> LarkClient:
    return LarkClient(
        executable=[sys.executable, fake_lark.executable],
        **kwargs,
    )


def test_fetch_uses_full_xml_user_identity(fake_lark):
    client = _client(fake_lark)
    response = client.fetch(parse_document_ref(DOC_URL))
    assert response["ok"] is True
    assert fake_lark.last_argv == [
        "docs",
        "+fetch",
        "--doc",
        DOC_URL,
        "--doc-format",
        "xml",
        "--detail",
        "full",
        "--as",
        "user",
        "--format",
        "json",
    ]


def test_update_requires_revision_and_block_replace(fake_lark):
    client = _client(fake_lark)
    client.replace_block(RESOLVED_REF, "blk1", "<p>新文本</p>", 9)
    assert "str_replace" not in fake_lark.last_argv
    assert "overwrite" not in fake_lark.last_argv
    assert fake_lark.last_argv[fake_lark.last_argv.index("--revision-id") + 1] == "9"
    assert fake_lark.last_argv[fake_lark.last_argv.index("--command") + 1] == (
        "block_replace"
    )


def test_hostile_url_and_xml_remain_single_argv_elements(fake_lark):
    client = _client(fake_lark)
    hostile_xml = '<p>a &amp; b; echo hi</p><p onclick="x">y</p>'
    client.replace_block(RESOLVED_REF, "blk;rm", hostile_xml, 3)
    argv = fake_lark.last_argv
    assert hostile_xml in argv
    assert "blk;rm" in argv
    assert all(isinstance(item, str) for item in argv)


def test_probe_returns_version_when_capabilities_exist(fake_lark):
    client = _client(fake_lark)
    version = client.probe()
    assert "fake" in version.lower() or "lark-cli" in version.lower()


def test_missing_executable_is_not_retryable(tmp_path):
    client = LarkClient(executable=str(tmp_path / "no-such-lark-cli"))
    with pytest.raises(LarkCliError) as exc:
        client.probe()
    assert exc.value.kind == "missing_executable"
    assert exc.value.retryable is False


def test_timeout_is_retryable(fake_lark, monkeypatch):
    monkeypatch.setenv("FAKE_LARK_MODE", "sleep")
    monkeypatch.setenv("FAKE_LARK_SLEEP", "2")
    client = _client(fake_lark, fetch_timeout=0.2)
    with pytest.raises(LarkCliError) as exc:
        client.fetch(parse_document_ref(DOC_URL))
    assert exc.value.kind == "timeout"
    assert exc.value.retryable is True


def test_nonzero_exit_normalized(fake_lark, monkeypatch):
    monkeypatch.setenv("FAKE_LARK_MODE", "nonzero")
    client = _client(fake_lark)
    with pytest.raises(LarkCliError) as exc:
        client.fetch(parse_document_ref(DOC_URL))
    assert exc.value.kind in {"process_error", "nonzero_exit"}
    assert "boom" not in str(exc.value.details)


def test_malformed_json_fails_closed(fake_lark, monkeypatch):
    monkeypatch.setenv("FAKE_LARK_MODE", "bad_json")
    client = _client(fake_lark)
    with pytest.raises(LarkCliError) as exc:
        client.fetch(parse_document_ref(DOC_URL))
    assert exc.value.kind == "invalid_json"


def test_ok_false_fails_closed(fake_lark, monkeypatch):
    monkeypatch.setenv("FAKE_LARK_MODE", "ok_false")
    client = _client(fake_lark)
    with pytest.raises(LarkCliError) as exc:
        client.fetch(parse_document_ref(DOC_URL))
    assert exc.value.kind == "network"
    assert exc.value.retryable is True


def test_partial_success_is_failure(fake_lark, monkeypatch):
    monkeypatch.setenv("FAKE_LARK_MODE", "partial_success")
    client = _client(fake_lark)
    with pytest.raises(LarkCliError) as exc:
        client.replace_block(RESOLVED_REF, "blk1", "<p>x</p>", 1)
    assert exc.value.kind == "partial_success"
    assert exc.value.retryable is False


def test_missing_revision_fails_closed(fake_lark, monkeypatch):
    monkeypatch.setenv("FAKE_LARK_MODE", "missing_revision")
    client = _client(fake_lark)
    with pytest.raises(LarkCliError) as exc:
        client.fetch(parse_document_ref(DOC_URL))
    assert exc.value.kind == "missing_revision"


def test_stdout_over_limit(fake_lark, monkeypatch):
    monkeypatch.setenv("FAKE_LARK_MODE", "huge_stdout")
    client = _client(fake_lark)
    with pytest.raises(LarkCliError) as exc:
        client.fetch(parse_document_ref(DOC_URL))
    assert exc.value.kind == "output_limit"
    assert exc.value.retryable is False


def test_stderr_over_limit(fake_lark, monkeypatch):
    monkeypatch.setenv("FAKE_LARK_MODE", "huge_stderr")
    client = _client(fake_lark)
    with pytest.raises(LarkCliError) as exc:
        client.fetch(parse_document_ref(DOC_URL))
    assert exc.value.kind == "output_limit"


@pytest.mark.parametrize(
    ("mode", "kind"),
    [
        ("auth", "auth"),
        ("scope", "scope"),
        ("permission", "permission"),
    ],
)
def test_auth_scope_permission_kinds(fake_lark, monkeypatch, mode, kind):
    monkeypatch.setenv("FAKE_LARK_MODE", mode)
    client = _client(fake_lark)
    with pytest.raises(LarkCliError) as exc:
        client.fetch(parse_document_ref(DOC_URL))
    assert exc.value.kind == kind
    assert "stdout" not in exc.value.details
    if kind == "scope":
        assert exc.value.details.get("missing_scopes") == ["docs:read"]
