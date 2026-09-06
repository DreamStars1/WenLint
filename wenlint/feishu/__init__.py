"""Feishu Docx/Wiki adapter public exports for WenLint 0.2."""

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


def __getattr__(name: str):
    """Lazy-load the CLI entry to avoid runpy double-import warnings.

    Args:
        name: Attribute name requested from the package.

    Returns:
        The CLI ``main`` function when requested.

    Raises:
        AttributeError: For unknown attributes.
    """
    if name == "main":
        from wenlint.feishu.cli import main as cli_main

        return cli_main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
