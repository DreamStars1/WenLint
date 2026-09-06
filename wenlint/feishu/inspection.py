"""Read-only Feishu document inspection orchestration.

Fetch once, project, scan with the existing WenLint core, bind coordinates, and
emit structured JSON. This module never calls document update APIs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wenlint.feishu.document import DocumentRefError, resolve_fetched_docx_ref
from wenlint.feishu.findings import bind_findings
from wenlint.feishu.lark import LarkCliError, LarkClient
from wenlint.feishu.models import DocumentRef, InspectionReport
from wenlint.feishu.projection import XmlSafetyError, project_xml
from wenlint.scanner import scan_text


def inspect_document(
    client: LarkClient,
    ref: DocumentRef,
    profile: str = "general",
) -> InspectionReport:
    """Fetch, project, scan, and bind a Feishu document without writing.

    Args:
        client: Bounded ``lark-cli`` adapter.
        ref: Docx/Wiki reference; Wiki is resolved from fetch metadata.
        profile: WenLint profile name.

    Returns:
        Structured inspection report.

    Raises:
        LarkCliError: When fetch payloads lack required metadata.
        XmlSafetyError: When XML cannot be safely projected.
        DocumentRefError: When resolved metadata is incomplete.
    """
    payload = client.fetch(ref)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise LarkCliError(
            "invalid_response",
            "fetch response is missing data object",
            retryable=False,
        )
    document = data.get("document")
    if not isinstance(document, Mapping):
        raise LarkCliError(
            "invalid_response",
            "fetch response is missing document metadata",
            retryable=False,
        )
    if "revision_id" not in document:
        raise LarkCliError(
            "missing_revision",
            "fetch response is missing document revision_id",
            retryable=False,
        )
    content = data.get("content")
    if not isinstance(content, str) or not content:
        raise LarkCliError(
            "invalid_response",
            "fetch response is missing XML content",
            retryable=False,
        )

    document_id = str(document.get("document_id") or "")
    canonical_url = str(document.get("url") or "")
    if not document_id or not canonical_url:
        raise LarkCliError(
            "unresolved_document",
            "fetch response did not resolve a Docx document id and URL",
            retryable=False,
        )

    try:
        resolved = resolve_fetched_docx_ref(ref, document_id, canonical_url)
    except DocumentRefError as exc:
        raise LarkCliError(
            getattr(exc, "kind", "unresolved_document"),
            str(exc),
            retryable=False,
        ) from exc
    raw_revision = document["revision_id"]
    if isinstance(raw_revision, bool) or not isinstance(raw_revision, int):
        raise LarkCliError(
            "invalid_response",
            "fetch response revision_id must be an integer",
            retryable=False,
        )
    revision_id = raw_revision
    snapshot = project_xml(content, resolved, revision_id)
    raw_findings = scan_text(snapshot.projection, profile=profile)
    public_findings = [_public_finding(item, snapshot.projection) for item in raw_findings]
    bound = bind_findings(snapshot, public_findings)
    return InspectionReport(
        ok=True,
        source={
            "kind": "feishu",
            "document_id": document_id,
            "revision_id": revision_id,
            "url": resolved.canonical_url,
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
