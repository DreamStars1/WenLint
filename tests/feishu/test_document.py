"""Document URL parsing and immutable Feishu domain models."""
from __future__ import annotations

import dataclasses

import pytest

from wenlint.feishu.document import DocumentRefError, parse_document_ref
from wenlint.feishu.models import (
    ApprovedSectionPlan,
    BoundFinding,
    DocumentRef,
    DocumentSnapshot,
    InspectionReport,
    Patch,
    Section,
    SourceSpan,
)


@pytest.mark.parametrize(
    ("url", "kind", "token"),
    [
        ("https://acme.feishu.cn/docx/DocToken", "docx", "DocToken"),
        ("https://acme.feishu.cn/wiki/WikiToken", "wiki", "WikiToken"),
        ("https://acme.larksuite.com/docx/DocToken#share-AbC", "docx", "DocToken"),
    ],
)
def test_parse_supported_document_urls(url, kind, token):
    ref = parse_document_ref(url)
    assert (ref.kind, ref.input_token) == (kind, token)
    assert ref.input_url.partition("?")[0].startswith("https://")
    assert ref.document_id is None
    assert ref.canonical_url is None


@pytest.mark.parametrize(
    "raw",
    ["http://acme.feishu.cn/docx/x", "https://acme.feishu.cn/sheets/x", "docx-token"],
)
def test_reject_unsupported_or_ambiguous_input(raw):
    with pytest.raises(DocumentRefError):
        parse_document_ref(raw)


def test_rejects_url_userinfo_and_empty_token():
    with pytest.raises(DocumentRefError):
        parse_document_ref("https://user:pass@acme.feishu.cn/docx/DocToken")
    with pytest.raises(DocumentRefError):
        parse_document_ref("https://acme.feishu.cn/docx/")


def test_strips_query_but_keeps_share_anchor():
    ref = parse_document_ref(
        "https://acme.feishu.cn/docx/DocToken?from=share#share-AbC"
    )
    assert "?" not in ref.input_url
    assert ref.input_url.endswith("#share-AbC")


def test_all_models_are_frozen():
    for cls in (
        DocumentRef,
        SourceSpan,
        Section,
        DocumentSnapshot,
        BoundFinding,
        Patch,
        ApprovedSectionPlan,
        InspectionReport,
    ):
        assert cls.__dataclass_params__.frozen is True


def test_source_span_allows_synthetic_nulls():
    span = SourceSpan(
        projection_start=0,
        projection_end=2,
        block_id=None,
        node_path=None,
        source_start=0,
        source_end=0,
        writable=False,
    )
    assert span.block_id is None
    assert span.node_path is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        span.writable = True  # type: ignore[misc]
