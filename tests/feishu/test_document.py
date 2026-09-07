"""Document URL parsing and immutable Feishu domain models."""
from __future__ import annotations

import dataclasses

import pytest

from wenlint.feishu.document import DocumentRefError, parse_document_ref
from wenlint.feishu.models import (
    ApprovedSectionPlan,
    ApplyResult,
    BoundFinding,
    DocumentRef,
    DocumentSnapshot,
    FindingLocation,
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


def test_mapping_fields_copy_input_and_reject_item_assignment():
    finding_src = {"rule": "H002", "text": "可能"}
    source_src = {"document_id": "DocToken", "revision_id": 1}
    details_src = {"kind": "ok", "count": 1}

    bound = BoundFinding(
        finding=finding_src,
        section=None,
        location=FindingLocation(
            block_id=None,
            block_url=None,
            node_path=None,
            mapping_status="unmapped",
            writable=False,
            reason="unmapped",
        ),
    )
    report = InspectionReport(
        ok=True,
        source=source_src,
        sections=(),
        findings=(),
    )
    result = ApplyResult(
        status="success",
        applied_patch_ids=(),
        unapplied_patch_ids=(),
        reconfirm_patch_ids=(),
        revision_id=1,
        message="ok",
        details=details_src,
    )

    finding_src["rule"] = "MUTATED"
    source_src["document_id"] = "MUTATED"
    details_src["kind"] = "MUTATED"
    assert bound.finding["rule"] == "H002"
    assert report.source["document_id"] == "DocToken"
    assert result.details["kind"] == "ok"

    with pytest.raises(TypeError):
        bound.finding["rule"] = "x"  # type: ignore[index]
    with pytest.raises(TypeError):
        report.source["document_id"] = "x"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.details["kind"] = "x"  # type: ignore[index]

    assert report.to_dict()["source"]["document_id"] == "DocToken"
    assert result.to_dict()["details"]["kind"] == "ok"


def test_bound_finding_rule_returns_id_or_empty_string():
    location = FindingLocation(
        block_id=None,
        block_url=None,
        node_path=None,
        mapping_status="unmapped",
        writable=False,
        reason="unmapped",
    )
    present = BoundFinding(finding={"rule": "H002"}, section=None, location=location)
    missing = BoundFinding(finding={}, section=None, location=location)
    assert present.rule == "H002"
    assert missing.rule == ""
    assert "Returns:" in (BoundFinding.rule.__doc__ or "")
