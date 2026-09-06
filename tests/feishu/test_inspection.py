"""Tests for read-only Feishu inspection orchestration."""
from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.inspection import inspect_document
from wenlint.feishu.lark import LarkCliError

REF = parse_document_ref("https://acme.feishu.cn/docx/DocToken")
WIKI_REF = parse_document_ref("https://acme.feishu.cn/wiki/WikiToken")


class FakeClient:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.fetch_calls = 0
        self.replace_calls: list[tuple] = []
        self.payload = payload or {
            "ok": True,
            "data": {
                "document": {
                    "document_id": "DocToken",
                    "revision_id": 12,
                    "url": "https://acme.feishu.cn/docx/DocToken",
                },
                "content": (
                    '<h1 block-id="blkTitle">标题</h1>'
                    '<p block-id="blkParagraph">普通正文可能含糊。</p>'
                ),
            },
        }

    def fetch(self, ref):
        self.fetch_calls += 1
        return self.payload

    def replace_block(self, *args, **kwargs):
        self.replace_calls.append((args, kwargs))
        raise AssertionError("inspect must never update")


def test_inspect_fetches_once_and_never_updates():
    client = FakeClient()
    report = inspect_document(client, REF, profile="formal")
    assert client.fetch_calls == 1
    assert client.replace_calls == []
    assert report.source["identity"] == "user"
    assert report.source["revision_id"] == 12
    assert report.ok is True
    data = report.to_dict()
    assert "sections" in data
    assert "findings" in data
    if data["findings"]:
        finding = data["findings"][0]
        assert "location" in finding
        assert "section" in finding


def test_wiki_uses_returned_document_id_and_canonical_url():
    client = FakeClient(
        {
            "ok": True,
            "data": {
                "document": {
                    "document_id": "ResolvedDoc",
                    "revision_id": 3,
                    "url": "https://acme.feishu.cn/docx/ResolvedDoc",
                },
                "content": '<p block-id="blk">正文。</p>',
            },
        }
    )
    report = inspect_document(client, WIKI_REF)
    assert report.source["document_id"] == "ResolvedDoc"
    assert report.source["url"] == "https://acme.feishu.cn/docx/ResolvedDoc"


def test_malformed_fetch_fails_without_partial_findings():
    client = FakeClient(
        {
            "ok": True,
            "data": {
                "document": {"document_id": "DocToken"},
                "content": "<p>x</p>",
            },
        }
    )
    with pytest.raises(LarkCliError):
        inspect_document(client, REF)
