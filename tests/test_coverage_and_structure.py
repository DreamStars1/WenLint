"""Coverage, heading structure, and table-cell scanning (spec 2026-09-08)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from wenlint.feishu.document import parse_document_ref
from wenlint.feishu.findings import bind_findings
from wenlint.feishu.inspection import inspect_document
from wenlint.feishu.models import FetchedDocument, InspectionReport
from wenlint.feishu.patches import PatchValidationError, validate_patches
from wenlint.feishu.projection import project_xml
from wenlint.feishu.models import ApprovedSectionPlan, Patch
from wenlint.markdown import classify_lines, is_table_delimiter_row, line_role
from wenlint.scanner import scan_text

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "product_structure_sample.md"
REF = parse_document_ref("https://acme.feishu.cn/docx/DocToken")
RESOLVED = dataclasses.replace(
    REF,
    document_id="DocToken",
    canonical_url="https://acme.feishu.cn/docx/DocToken",
)

EXPECTED_COVERAGE = {
    "static": {
        "paragraphs": "scanned",
        "list_items": "scanned",
        "blockquotes": "scanned",
        "headings": "structure_only",
        "table_cells": "scanned",
        "code": "excluded",
        "embedded_resources": "excluded",
    },
    "semantic_review": "not_run",
}


def test_empty_atx_heading_produces_doc001():
    hits = [h for h in scan_text("###\n\n正文。\n") if h["rule_id"] == "DOC001"]
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["severity"] == "warning"
    assert hits[0]["category"] == "文档结构"
    assert hits[0]["match"] == ""
    assert hits[0]["review_hint"]


def test_numbered_heading_gap_product_doc002():
    text = "### 3.1 数据来源\n\n正文。\n\n### 3.3 其它来源\n"
    hits = [h for h in scan_text(text, profile="product") if h["rule_id"] == "DOC002"]
    assert len(hits) == 1
    assert hits[0]["line"] == 5
    assert hits[0]["severity"] == "candidate"
    assert "3.1" in hits[0]["message"] and "3.3" in hits[0]["message"]


def test_contiguous_numbered_headings_no_doc002():
    text = "### 3.1 数据来源\n\n### 3.2 其它来源\n"
    hits = [h for h in scan_text(text, profile="product") if h["rule_id"] == "DOC002"]
    assert hits == []


def test_numbered_headings_under_different_parents_not_compared():
    text = (
        "## 3 模块甲\n\n"
        "### 3.1 甲子\n\n"
        "## 4 模块乙\n\n"
        "### 4.3 乙子\n"
    )
    hits = [h for h in scan_text(text, profile="product") if h["rule_id"] == "DOC002"]
    assert hits == []


def test_doc002_nonnumeric_parents_use_stable_per_occurrence_identity():
    """Sibling numbers under distinct nonnumeric parents must not compare."""
    text = (
        "## 模块甲\n\n"
        "### 3.1 甲子\n\n"
        "## 模块乙\n\n"
        "### 3.3 乙子\n"
    )
    hits = [h for h in scan_text(text, profile="product") if h["rule_id"] == "DOC002"]
    assert hits == []


def test_general_profile_disables_doc002():
    text = "### 3.1 数据来源\n\n### 3.3 其它来源\n"
    hits = [h for h in scan_text(text, profile="general") if h["rule_id"] == "DOC002"]
    assert hits == []


def test_markdown_table_cliche_reports_column_at_word_start():
    text = "| 说明 |\n|---|\n| 总而言之 |\n"
    hits = [h for h in scan_text(text) if h["rule_id"] == "C001"]
    assert len(hits) == 1
    assert hits[0]["line"] == 3
    line = text.splitlines()[2]
    assert hits[0]["col"] == line.index("总而言之") + 1


def test_table_delimiter_row_produces_no_finding():
    text = "| 列A |\n| :---: |\n| ok |\n"
    hits = scan_text(text)
    assert not any(h["line"] == 2 for h in hits)


def test_table_cell_long_sentence_scored_independently():
    long_a = "甲" * 90
    long_b = "乙" * 90
    text = f"| {long_a} | {long_b} |\n"
    hits = [h for h in scan_text(text) if h["rule_id"] == "S001"]
    assert len(hits) == 2
    assert {h["line"] for h in hits} == {1}


def test_gfm_table_without_leading_pipes_scans_cells_independently():
    long_a = "甲" * 90
    long_b = "乙" * 90
    text = (
        f"说明 | 备注\n"
        f"--- | ---\n"
        f"{long_a} | {long_b}\n"
    )
    hits = [h for h in scan_text(text) if h["rule_id"] == "S001"]
    assert len(hits) == 2
    assert {h["line"] for h in hits} == {3}


def test_prose_pipe_not_misclassified_as_table():
    text = "请在 A | B 两种方案中择一，并说明理由。\n"
    hits = scan_text(text)
    assert not any(h["rule_id"] == "S001" for h in hits)
    # Ordinary prose still receives lexical scanning (not skipped as table).
    assert line_role(text.strip()) == "paragraph"


def test_table_shaped_content_inside_fenced_code_not_scanned():
    """Document-level exclusions must suppress table-cell scanning."""
    text = (
        "```\n"
        "说明 | 备注\n"
        "--- | ---\n"
        "总而言之 | 可能含糊\n"
        "```\n"
    )
    hits = [
        h for h in scan_text(text)
        if h["rule_id"] in {"C001", "H002"}
    ]
    assert hits == []


def test_table_shaped_content_inside_front_matter_not_scanned():
    text = (
        "---\n"
        "说明 | 备注\n"
        "--- | ---\n"
        "总而言之 | 可能含糊\n"
        "---\n"
        "正文。\n"
    )
    hits = [
        h for h in scan_text(text)
        if h["rule_id"] in {"C001", "H002"}
    ]
    assert hits == []


def test_table_shaped_content_inside_html_comment_not_scanned():
    text = (
        "<!--\n"
        "说明 | 备注\n"
        "--- | ---\n"
        "总而言之 | 可能含糊\n"
        "-->\n"
        "正文。\n"
    )
    hits = [
        h for h in scan_text(text)
        if h["rule_id"] in {"C001", "H002"}
    ]
    assert hits == []


def test_partial_html_comment_inside_table_row_excludes_comment_spans():
    """Multi-line HTML comments that start mid-cell must stay excluded.

    Table scanners historically treated the document mask as an all-blank
    guard, then re-parsed/scanned the raw row — leaking C001/H002 from the
    comment interior while still needing visible post-``-->`` cells to lint.
    """
    text = (
        "| 说明 | 备注 |\n"
        "| --- | --- |\n"
        "| 正文 <!-- 总而言之 | 可能含糊\n"
        "| 注释继续 | 可能\n"
        "| --> 总而言之 | 正文 |\n"
    )
    hits = [
        h for h in scan_text(text)
        if h["rule_id"] in {"C001", "H002"}
    ]
    assert not any(h["line"] in {3, 4} for h in hits)
    c001 = [h for h in hits if h["rule_id"] == "C001"]
    assert len(c001) == 1
    assert c001[0]["line"] == 5
    assert c001[0]["match"] == "总而言之"
    line5 = text.splitlines()[4]
    assert c001[0]["col"] == line5.index("总而言之") + 1
    assert not any(h["rule_id"] == "H002" for h in hits)


def test_gfm_delimiter_requires_three_hyphens():
    """GFM delimiter cells need >=3 hyphens; `- | -` is not a table."""
    assert is_table_delimiter_row("- | -") is False
    assert is_table_delimiter_row("| - | - |") is False
    assert is_table_delimiter_row("--- | ---") is True
    assert is_table_delimiter_row("| --- | :---: |") is True

    text = "说明 | 备注\n- | -\n总而言之 | 可能含糊\n"
    roles = classify_lines(text.splitlines())
    assert "table" not in roles
    assert roles[0] == "paragraph"
    assert roles[2] == "paragraph"
    # Middle line may be list_item (`- ` prefix); must not promote a GFM table.


def test_empty_atx_with_closing_hash_sequences_are_doc001():
    for line in ("### ###", "### #"):
        hits = [h for h in scan_text(line + "\n") if h["rule_id"] == "DOC001"]
        assert len(hits) == 1, line
    # Visible title must not disappear when trailing hashes are content-like.
    keep = [h for h in scan_text("### 模块甲\n") if h["rule_id"] == "DOC001"]
    assert keep == []
    titled = [h for h in scan_text("### 标题 ###\n") if h["rule_id"] == "DOC001"]
    assert titled == []


def test_heading_like_lines_inside_fenced_code_not_doc001_or_doc002():
    """Globally excluded fence bodies must not feed heading structure rules."""
    text = (
        "~~~text\n"
        "###\n"
        "### 3.1 甲\n"
        "### 3.3 乙\n"
        "~~~\n"
    )
    hits = [
        h for h in scan_text(text, profile="product")
        if h["rule_id"] in {"DOC001", "DOC002"}
    ]
    assert hits == []


def test_heading_like_lines_inside_front_matter_not_doc001_or_doc002():
    text = (
        "---\n"
        "###\n"
        "### 3.1 甲\n"
        "### 3.3 乙\n"
        "---\n"
        "正文。\n"
    )
    hits = [
        h for h in scan_text(text, profile="product")
        if h["rule_id"] in {"DOC001", "DOC002"}
    ]
    assert hits == []


def test_heading_like_lines_inside_html_comment_not_doc001_or_doc002():
    text = (
        "<!--\n"
        "###\n"
        "### 3.1 甲\n"
        "### 3.3 乙\n"
        "-->\n"
        "正文。\n"
    )
    hits = [
        h for h in scan_text(text, profile="product")
        if h["rule_id"] in {"DOC001", "DOC002"}
    ]
    assert hits == []


def test_real_empty_heading_after_excluded_block_still_doc001():
    text = (
        "~~~text\n"
        "###\n"
        "### 3.1 甲\n"
        "~~~\n"
        "\n"
        "###\n"
    )
    hits = [h for h in scan_text(text, profile="product") if h["rule_id"] == "DOC001"]
    assert len(hits) == 1
    assert hits[0]["line"] == 6


def test_real_numbered_heading_gap_after_excluded_block_still_doc002():
    text = (
        "~~~text\n"
        "### 3.1 甲\n"
        "### 3.3 乙\n"
        "~~~\n"
        "\n"
        "### 3.1 甲\n"
        "\n"
        "### 3.3 乙\n"
    )
    hits = [h for h in scan_text(text, profile="product") if h["rule_id"] == "DOC002"]
    assert len(hits) == 1
    assert hits[0]["line"] == 8


def test_inline_code_heading_title_is_not_empty_doc001():
    """Mask blanks inline code; emptiness must still use the raw heading title."""
    text = "### `模块标识符`\n"
    hits = [h for h in scan_text(text) if h["rule_id"] == "DOC001"]
    assert hits == []


def test_feishu_nested_table_xml_projects_cells_exact_nonwritable():
    xml = (
        '<h1 id="t">标题</h1>'
        '<table id="tbl">'
        "<colgroup><col/><col/></colgroup>"
        "<tbody>"
        "<tr>"
        '<td><p id="p1">总而言之</p></td>'
        '<td><p id="p2">可能含糊</p></td>'
        "</tr>"
        "</tbody>"
        "</table>"
    )
    snapshot = project_xml(xml, RESOLVED, 1)
    assert "总而言之" in snapshot.projection
    assert "可能含糊" in snapshot.projection
    # Full path from table root: colgroup=0, tbody=1, tr=0, td=0, p=0 → (1,0,0,0)
    text_spans = [
        s for s in snapshot.source_map
        if s.node_path is not None and snapshot.projection[s.projection_start:s.projection_end]
    ]
    by_text = {
        snapshot.projection[s.projection_start:s.projection_end]: s
        for s in text_spans
        if snapshot.projection[s.projection_start:s.projection_end] in {"总而言之", "可能含糊"}
    }
    assert by_text["总而言之"].node_path == (1, 0, 0, 0)
    assert by_text["可能含糊"].node_path == (1, 0, 1, 0)
    raw = scan_text(snapshot.projection)
    public = []
    for item in raw:
        if item["rule_id"] not in {"C001", "H002"}:
            continue
        public.append(
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
        )
    assert {p["rule"] for p in public} >= {"C001", "H002"}
    bound = bind_findings(snapshot, public)
    assert bound
    for item in bound:
        assert item.location.writable is False
        assert item.location.mapping_status == "exact"
        assert item.location.reason == "table_cell"
        assert item.location.block_id == "tbl"


def test_feishu_table_lexical_hits_are_exact_but_not_writable():
    xml = (
        '<h1 block-id="t">标题</h1>'
        '<table block-id="tbl">'
        "<tr>"
        "<td>总而言之</td>"
        "<td>可能含糊</td>"
        "</tr>"
        "</table>"
    )
    snapshot = project_xml(xml, RESOLVED, 1)
    raw = scan_text(snapshot.projection)
    public = []
    for item in raw:
        if item["rule_id"] not in {"C001", "H002"}:
            continue
        public.append(
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
        )
    assert {p["rule"] for p in public} >= {"C001", "H002"}
    bound = bind_findings(snapshot, public)
    assert bound
    for item in bound:
        assert item.location.writable is False
        assert item.location.mapping_status == "exact"
        assert item.location.reason == "table_cell"
        assert item.location.block_id


def test_empty_feishu_h3_doc001_not_writable():
    xml = '<h3 block-id="h"></h3><p block-id="p">正文。</p>'
    snapshot = project_xml(xml, RESOLVED, 1)
    raw = [h for h in scan_text(snapshot.projection) if h["rule_id"] == "DOC001"]
    assert len(raw) == 1
    public = [
        {
            "rule": "DOC001",
            "type": "lint",
            "severity": "warning",
            "category": "文档结构",
            "message": raw[0]["message"],
            "review_hint": raw[0]["review_hint"],
            "line": raw[0]["line"],
            "column": raw[0]["col"],
            "text": raw[0]["match"],
            "sentence": raw[0]["sentence"],
            "before": None,
            "after": None,
        }
    ]
    bound = bind_findings(snapshot, public)
    assert bound[0].location.writable is False


def test_inspection_report_always_emits_coverage():
    report = InspectionReport(ok=True, source={"kind": "feishu"}, sections=(), findings=())
    data = report.to_dict()
    assert data["coverage"] == EXPECTED_COVERAGE
    assert data["findings"] == []


def test_empty_findings_still_mark_semantic_review_not_run():
    class FakeClient:
        def fetch(self, ref):
            return FetchedDocument(
                ref=RESOLVED,
                revision_id=1,
                xml='<p block-id="p">干净正文。</p>',
            )

        def replace_block(self, *args, **kwargs):
            raise AssertionError("inspect must never update")

    report = inspect_document(FakeClient(), REF)
    data = report.to_dict()
    assert data["findings"] == []
    assert data["coverage"]["semantic_review"] == "not_run"
    assert data["coverage"]["static"]["table_cells"] == "scanned"


def test_product_fixture_yields_doc001_doc002_and_coverage_semantics():
    text = FIXTURE.read_text(encoding="utf-8")
    hits = scan_text(text, profile="product")
    assert len([h for h in hits if h["rule_id"] == "DOC001"]) == 1
    assert len([h for h in hits if h["rule_id"] == "DOC002"]) == 1
    # status=0 business contradiction is intentionally not a static finding
    assert not any("status=0" in (h.get("match") or "") for h in hits)


def test_readme_and_skill_distinguish_zero_hit_from_semantic_pass():
    phrase = "静态规则未命中 ≠ 全文已经语义审查 ≠ 文档没有问题"
    assert phrase in Path("README.md").read_text(encoding="utf-8")
    assert phrase in Path("SKILL.md").read_text(encoding="utf-8")
    skill = Path("SKILL.md").read_text(encoding="utf-8")
    assert "详细" in skill and "全文" in skill
    assert "幂等" in skill and "验收条件" in skill
    assert "M001" in skill and "M002" in skill
    assert "讨论过程" in skill and "纠偏说明" in skill
    assert "当前稿自洽与上下文独立" in skill

    readme = Path("README.md").read_text(encoding="utf-8")
    assert "revision-history" in readme
    assert "context-dependent-transition" in readme


def test_apply_rejects_table_cell_and_structure_patches():
    xml = (
        '<h1 block-id="t">标题</h1>'
        '<table block-id="tbl"><tr><td>总而言之</td></tr></table>'
    )
    snapshot = project_xml(xml, RESOLVED, 1)
    section = snapshot.sections[0]
    plan = ApprovedSectionPlan(
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
                block_id="tbl",
                node_path=(0, 0),
                source_start=0,
                source_end=4,
                before="总而言之",
                after="因此",
                rule_id="C001",
                rationale="table rewrite",
            ),
        ),
    )
    try:
        validate_patches(snapshot, plan)
        raised = False
    except PatchValidationError:
        raised = True
    assert raised
