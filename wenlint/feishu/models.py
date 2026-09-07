"""Immutable Feishu domain models shared by inspect and apply paths.

Public models are frozen so inspection and writeback never mutate a shared
snapshot, reference, or approved plan in place. Mapping fields additionally
copy caller input into ``MappingProxyType`` so item assignment cannot mutate
serialized payloads in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence


@dataclass(frozen=True)
class DocumentRef:
    """Canonical or unresolved Feishu Docx/Wiki reference.

    Attributes:
        input_url: HTTPS URL with query parameters removed; share anchors may
            remain for reading.
        kind: Product kind derived from the path segment.
        input_token: Token from the input URL path.
        document_id: Actual Docx document id after a validated fetch; ``None``
            until fetch resolves Wiki or confirms Docx.
        canonical_url: Canonical Docx URL after fetch; ``None`` until resolved.
    """

    input_url: str
    kind: Literal["docx", "wiki"]
    input_token: str
    document_id: str | None = None
    canonical_url: str | None = None


@dataclass(frozen=True)
class SourceSpan:
    """One contiguous mapping from analysis projection to XML source text.

    Attributes:
        projection_start: Inclusive start offset in the analysis projection.
        projection_end: Exclusive end offset in the analysis projection.
        block_id: Feishu block id for real text; ``None`` for synthetic spans.
        node_path: Path of child indexes to the text node; ``None`` when
            synthetic.
        source_start: Inclusive offset inside the XML text node.
        source_end: Exclusive offset inside the XML text node.
        writable: Whether automatic writeback may target this span.
    """

    projection_start: int
    projection_end: int
    block_id: str | None
    node_path: tuple[int, ...] | None
    source_start: int
    source_end: int
    writable: bool


@dataclass(frozen=True)
class Section:
    """One document chapter bounded by heading hierarchy.

    Attributes:
        locator: Stable structural locator including same-name sibling ordinals.
        title: Visible heading title, or a reserved label for the lead-in.
        level: Heading level; ``0`` for synthetic lead-in content.
        block_ids: Block ids belonging to this section in document order.
        fingerprint: SHA-256 hex digest of the section's canonical XML.
    """

    locator: str
    title: str
    level: int
    block_ids: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class DocumentSnapshot:
    """Immutable projected view of one XML ``full`` fetch.

    Attributes:
        ref: Resolved document reference used for this snapshot.
        revision_id: Document revision from the fetch response.
        xml: Exact XML body used for projection (not logged by callers).
        projection: Deterministic analysis text consumed by ``scan_text``.
        source_map: Character-level mapping from projection to XML nodes.
        sections: Ordered chapter boundaries with fingerprints.
    """

    ref: DocumentRef
    revision_id: int
    xml: str
    projection: str
    source_map: tuple[SourceSpan, ...]
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class FindingLocation:
    """Bound location metadata attached to a Feishu finding.

    Attributes:
        block_id: Target block when mapping succeeded.
        block_url: Deep link when a block id is known.
        node_path: XML text-node path when uniquely mapped.
        mapping_status: Stable status such as ``exact`` or ``unmapped``.
        writable: Whether the finding may enter an approved patch.
        reason: Failure reason when not writable; ``None`` on exact maps.
        source_start: Inclusive source offset when mapped.
        source_end: Exclusive source offset when mapped.
    """

    block_id: str | None
    block_url: str | None
    node_path: tuple[int, ...] | None
    mapping_status: str
    writable: bool
    reason: str | None
    source_start: int | None = None
    source_end: int | None = None


@dataclass(frozen=True)
class BoundFinding:
    """Scanner finding bound to Feishu section and source coordinates.

    Attributes:
        finding: Original scanner finding fields (rule, message, offsets, …).
        section: Section summary when a unique chapter owns the match.
        location: Mapping outcome used by Skill and writeback gates.
    """

    finding: Mapping[str, Any]
    section: Section | None
    location: FindingLocation

    def __post_init__(self) -> None:
        """Copy ``finding`` into an immutable mapping proxy.

        Raises:
            TypeError: If ``finding`` is not a mapping.
        """
        object.__setattr__(self, "finding", MappingProxyType(dict(self.finding)))

    @property
    def rule(self) -> str:
        """Return the WenLint rule id from the underlying finding.

        Returns:
            Rule id as a string, or ``""`` when ``finding`` omits ``rule``.
        """
        return str(self.finding.get("rule", ""))


@dataclass(frozen=True)
class Patch:
    """One approved contiguous text replacement inside a single XML node.

    Attributes:
        patch_id: Caller-supplied unique id within a manifest.
        section_locator: Chapter locator this patch was approved against.
        section_fingerprint: Fingerprint at approval time.
        block_id: Block containing the text node at planning time.
        node_path: Path to the text node inside the block.
        source_start: Inclusive offset in the text node for overlap checks.
        source_end: Exclusive offset in the text node for overlap checks.
        before: Exact original text that must still match before writing.
        after: Replacement text for the same contiguous range.
        rule_id: WenLint rule that motivated the change.
        rationale: Human-readable reason retained for audit output.
    """

    patch_id: str
    section_locator: str
    section_fingerprint: str
    block_id: str
    node_path: tuple[int, ...]
    source_start: int
    source_end: int
    before: str
    after: str
    rule_id: str
    rationale: str


@dataclass(frozen=True)
class ApprovedSectionPlan:
    """User-approved write plan for exactly one document section.

    Attributes:
        document_id: Actual Docx id the manifest targets.
        section_locator: Structural locator of the approved chapter.
        initial_fingerprint: Fingerprint observed when the user approved.
        base_revision: Document revision observed when the user approved.
        approved_patch_ids: Patch ids explicitly approved for this chapter.
        expected_fingerprints: Per-block-write expected fingerprints in order.
        patches: Full patch payloads validated with the manifest.
    """

    document_id: str
    section_locator: str
    initial_fingerprint: str
    base_revision: int
    approved_patch_ids: tuple[str, ...]
    expected_fingerprints: tuple[str, ...]
    patches: tuple[Patch, ...] = ()


@dataclass(frozen=True)
class InspectionReport:
    """Structured read-only inspection result for one Feishu document.

    Attributes:
        ok: Always ``True`` for successful reports; errors use stderr instead.
        source: Document identity and revision metadata.
        sections: Chapters discovered in the snapshot.
        findings: Bound findings ready for Skill classification.
    """

    ok: bool
    source: Mapping[str, Any]
    sections: tuple[Section, ...]
    findings: tuple[BoundFinding, ...]

    def __post_init__(self) -> None:
        """Copy ``source`` into an immutable mapping proxy.

        Raises:
            TypeError: If ``source`` is not a mapping.
        """
        object.__setattr__(self, "source", MappingProxyType(dict(self.source)))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to JSON-safe primitives.

        Returns:
            A dict matching the Feishu inspect JSON protocol.
        """
        return {
            "ok": self.ok,
            "source": dict(self.source),
            "sections": [
                {
                    "locator": section.locator,
                    "title": section.title,
                    "level": section.level,
                    "block_ids": list(section.block_ids),
                    "fingerprint": section.fingerprint,
                }
                for section in self.sections
            ],
            "findings": [_bound_finding_to_dict(item) for item in self.findings],
        }


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of applying one approved section plan.

    Attributes:
        status: ``success``, ``conflict``, or ``partial_failure``.
        applied_patch_ids: Patches verified after a successful write.
        unapplied_patch_ids: Patches that never wrote.
        reconfirm_patch_ids: Patches that need a fresh chapter approval.
        revision_id: Latest known revision after the attempt.
        message: Compact human-readable summary without document bodies.
        details: Safe structured extras such as conflict kinds.
    """

    status: Literal["success", "conflict", "partial_failure"]
    applied_patch_ids: tuple[str, ...]
    unapplied_patch_ids: tuple[str, ...]
    reconfirm_patch_ids: tuple[str, ...]
    revision_id: int | None
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Copy ``details`` into an immutable mapping proxy.

        Raises:
            TypeError: If ``details`` is not a mapping.
        """
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        """Serialize apply status without before/after text or block XML.

        Returns:
            JSON-safe status payload for stdout.
        """
        return {
            "ok": self.status == "success",
            "status": self.status,
            "applied_patch_ids": list(self.applied_patch_ids),
            "unapplied_patch_ids": list(self.unapplied_patch_ids),
            "reconfirm_patch_ids": list(self.reconfirm_patch_ids),
            "revision_id": self.revision_id,
            "message": self.message,
            "details": dict(self.details),
        }


def _bound_finding_to_dict(item: BoundFinding) -> dict[str, Any]:
    """Merge scanner fields with Feishu section/location metadata.

    Args:
        item: Bound finding to serialize.

    Returns:
        Flat finding dict for Skill consumption.
    """
    payload = dict(item.finding)
    if item.section is not None:
        payload["section"] = {
            "locator": item.section.locator,
            "title": item.section.title,
            "fingerprint": item.section.fingerprint,
        }
    else:
        payload["section"] = None
    loc = item.location
    payload["location"] = {
        "block_id": loc.block_id,
        "block_url": loc.block_url,
        "node_path": list(loc.node_path) if loc.node_path is not None else None,
        "mapping_status": loc.mapping_status,
        "writable": loc.writable,
        "reason": loc.reason,
        "source_start": loc.source_start,
        "source_end": loc.source_end,
    }
    return payload
