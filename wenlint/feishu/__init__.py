"""Feishu Docx/Wiki adapter public exports for WenLint 0.2."""

from wenlint.feishu.cli import main
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

__all__ = [
    "ApprovedSectionPlan",
    "ApplyResult",
    "BoundFinding",
    "DocumentRef",
    "DocumentRefError",
    "DocumentSnapshot",
    "FindingLocation",
    "InspectionReport",
    "Patch",
    "Section",
    "SourceSpan",
    "main",
    "parse_document_ref",
]
