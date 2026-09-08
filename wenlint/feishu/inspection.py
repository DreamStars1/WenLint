"""Read-only Feishu document inspection orchestration.

Fetch once, project, scan with the existing WenLint core, bind coordinates, and
emit structured JSON. This module never calls document update APIs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wenlint.feishu.findings import bind_findings
from wenlint.feishu.lark import DocumentGateway
from wenlint.feishu.models import DocumentRef, InspectionReport
from wenlint.feishu.projection import XmlSafetyError, project_xml
from wenlint.scanner import scan_text


def inspect_document(
    client: DocumentGateway,
    ref: DocumentRef,
    profile: str = "general",
) -> InspectionReport:
    """Fetch, project, scan, and bind a Feishu document without writing.

    Args:
        client: Document gateway returning normalized ``FetchedDocument``.
        ref: Docx/Wiki reference; Wiki is resolved from fetch metadata.
        profile: WenLint profile name.

    Returns:
        Structured inspection report.

    Raises:
        LarkCliError: When fetch fails closed.
        XmlSafetyError: When XML cannot be safely projected.
        DocumentRefError: When resolved metadata is incomplete.
    """
    fetched = client.fetch(ref)
    snapshot = project_xml(fetched.xml, fetched.ref, fetched.revision_id)
    raw_findings = scan_text(snapshot.projection, profile=profile)
    public_findings = [_public_finding(item, snapshot.projection) for item in raw_findings]
    bound = bind_findings(snapshot, public_findings)
    return InspectionReport(
        ok=True,
        source={
            "kind": "feishu",
            "document_id": fetched.ref.document_id,
            "revision_id": fetched.revision_id,
            "url": fetched.ref.canonical_url,
            "identity": "user",
        },
        sections=snapshot.sections,
        findings=bound,
    )


def _public_finding(finding: Mapping[str, Any], projection: str) -> dict[str, Any]:
    """Normalize scanner findings to the public JSON field names.

    Args:
        finding: Raw ``scan_text`` finding.
        projection: Analysis projection used for before/after context lines.

    Returns:
        Public finding dict without Feishu location metadata.
    """
    lines = projection.split("\n")
    line = int(finding["line"])
    return {
        "rule": finding["rule_id"],
        "type": "candidate" if finding["severity"] == "candidate" else "lint",
        "severity": finding["severity"],
        "category": finding["category"],
        "message": finding["message"],
        "review_hint": finding["review_hint"],
        "line": line,
        "column": finding["col"],
        "text": finding["match"],
        "sentence": finding["sentence"],
        "before": lines[line - 2] if line >= 2 else None,
        "after": lines[line] if line < len(lines) else None,
    }
