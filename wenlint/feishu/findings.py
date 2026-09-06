"""Bind scanner findings to Feishu SourceMap spans and sections.

Binding is exact and fail-closed: synthetic spans, cross-node ranges, unsupported
blocks, and text mismatches never become writable patches.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from wenlint.feishu.models import (
    BoundFinding,
    DocumentSnapshot,
    FindingLocation,
    Section,
    SourceSpan,
)


def bind_findings(
    snapshot: DocumentSnapshot,
    findings: Sequence[Mapping[str, object]],
) -> tuple[BoundFinding, ...]:
    """Convert scanner findings into Feishu-bound findings.

    Args:
        snapshot: Projected document with SourceMap and sections.
        findings: Public finding dicts using one-based line/column and ``text``.

    Returns:
        Bound findings in the same order as ``findings``.
    """
    line_starts = _line_starts(snapshot.projection)
    bound: list[BoundFinding] = []
    for finding in findings:
        start, end, reason = _projection_range(finding, snapshot.projection, line_starts)
        if reason is not None:
            bound.append(
                BoundFinding(
                    finding=dict(finding),
                    section=None,
                    location=FindingLocation(
                        block_id=None,
                        block_url=None,
                        node_path=None,
                        mapping_status=reason,
                        writable=False,
                        reason=reason,
                    ),
                )
            )
            continue
        assert start is not None and end is not None
        location, section = _bind_range(snapshot, start, end, str(finding.get("text", "")))
        bound.append(
            BoundFinding(
                finding=dict(finding),
                section=section,
                location=location,
            )
        )
    return tuple(bound)


def _line_starts(text: str) -> list[int]:
    """Precompute absolute offsets for each one-based line start.

    Args:
        text: Analysis projection.

    Returns:
        List where index ``line-1`` stores the absolute offset of that line.
    """
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _projection_range(
    finding: Mapping[str, object],
    projection: str,
    line_starts: list[int],
) -> tuple[int | None, int | None, str | None]:
    """Convert one-based line/column plus match text into projection offsets.

    Args:
        finding: Scanner finding with ``line``, ``column``/``col``, and ``text``.
        projection: Full analysis projection.
        line_starts: Precomputed line start offsets.

    Returns:
        ``(start, end, reason)``. On failure ``start``/``end`` are ``None`` and
        ``reason`` explains the mapping status.
    """
    line = int(finding.get("line") or 0)
    column = int(finding.get("column") or finding.get("col") or 0)
    match = str(finding.get("text") or finding.get("match") or "")
    if line < 1 or column < 1 or line > len(line_starts):
        return None, None, "unmapped"
    start = line_starts[line - 1] + (column - 1)
    if start < 0 or start > len(projection):
        return None, None, "unmapped"
    # S001 and similar may report empty matches; those stay report-only.
    if match == "":
        return start, start, "empty_match"
    end = start + len(match)
    if end > len(projection) or projection[start:end] != match:
        return None, None, "unmapped"
    return start, end, None


def _bind_range(
    snapshot: DocumentSnapshot,
    start: int,
    end: int,
    match: str,
) -> tuple[FindingLocation, Section | None]:
    """Bind an inclusive-exclusive projection range to source metadata.

    Args:
        snapshot: Document snapshot.
        start: Inclusive projection offset.
        end: Exclusive projection offset.
        match: Expected exact source text.

    Returns:
        Location metadata and owning section when uniquely determined.
    """
    if start == end:
        return (
            FindingLocation(
                block_id=None,
                block_url=None,
                node_path=None,
                mapping_status="empty_match",
                writable=False,
                reason="empty_match",
            ),
            None,
        )

    spans = [
        span
        for span in snapshot.source_map
        if span.projection_end > start and span.projection_start < end
    ]
    if not spans:
        return (
            FindingLocation(
                block_id=None,
                block_url=None,
                node_path=None,
                mapping_status="unmapped",
                writable=False,
                reason="unmapped",
            ),
            None,
        )

    if any(span.block_id is None or span.node_path is None for span in spans):
        return (
            FindingLocation(
                block_id=None,
                block_url=None,
                node_path=None,
                mapping_status="synthetic_span",
                writable=False,
                reason="synthetic_span",
            ),
            _section_for_spans(snapshot, spans),
        )

    block_ids = {span.block_id for span in spans}
    node_paths = {span.node_path for span in spans}
    if len(block_ids) != 1 or len(node_paths) != 1:
        return (
            FindingLocation(
                block_id=next(iter(block_ids)) if len(block_ids) == 1 else None,
                block_url=None,
                node_path=None,
                mapping_status="cross_node",
                writable=False,
                reason="cross_node",
            ),
            _section_for_spans(snapshot, spans),
        )

    if any(not span.writable for span in spans):
        return (
            FindingLocation(
                block_id=next(iter(block_ids)),
                block_url=_block_url(snapshot, next(iter(block_ids))),
                node_path=next(iter(node_paths)),
                mapping_status="unsupported_block",
                writable=False,
                reason="unsupported_block",
            ),
            _section_for_spans(snapshot, spans),
        )

    # Require contiguous coverage with no gaps between contributing spans.
    ordered = sorted(spans, key=lambda span: span.projection_start)
    covered = ordered[0].projection_start
    for span in ordered:
        if span.projection_start > covered:
            return (
                FindingLocation(
                    block_id=next(iter(block_ids)),
                    block_url=_block_url(snapshot, next(iter(block_ids))),
                    node_path=next(iter(node_paths)),
                    mapping_status="unmapped",
                    writable=False,
                    reason="unmapped",
                ),
                _section_for_spans(snapshot, spans),
            )
        covered = max(covered, span.projection_end)
    if ordered[0].projection_start > start or ordered[-1].projection_end < end:
        return (
            FindingLocation(
                block_id=next(iter(block_ids)),
                block_url=_block_url(snapshot, next(iter(block_ids))),
                node_path=next(iter(node_paths)),
                mapping_status="unmapped",
                writable=False,
                reason="unmapped",
            ),
            _section_for_spans(snapshot, spans),
        )

    source_start = None
    source_end = None
    for span in ordered:
        overlap_start = max(start, span.projection_start)
        overlap_end = min(end, span.projection_end)
        if overlap_start >= overlap_end:
            continue
        local_start = span.source_start + (overlap_start - span.projection_start)
        local_end = span.source_start + (overlap_end - span.projection_start)
        source_start = local_start if source_start is None else min(source_start, local_start)
        source_end = local_end if source_end is None else max(source_end, local_end)

    block_id = next(iter(block_ids))
    node_path = next(iter(node_paths))
    assert source_start is not None and source_end is not None
    actual = _extract_source_text(snapshot, block_id, node_path, source_start, source_end)
    if actual != match:
        return (
            FindingLocation(
                block_id=block_id,
                block_url=_block_url(snapshot, block_id),
                node_path=node_path,
                mapping_status="source_mismatch",
                writable=False,
                reason="source_mismatch",
                source_start=source_start,
                source_end=source_end,
            ),
            _section_for_spans(snapshot, spans),
        )

    # Duplicate identical source elsewhere does not affect this exact map; the
    # coordinate path already selected one contiguous writable node.
    section = _section_for_block(snapshot, block_id)
    return (
        FindingLocation(
            block_id=block_id,
            block_url=_block_url(snapshot, block_id),
            node_path=node_path,
            mapping_status="exact",
            writable=True,
            reason=None,
            source_start=source_start,
            source_end=source_end,
        ),
        section,
    )


def _extract_source_text(
    snapshot: DocumentSnapshot,
    block_id: str,
    node_path: tuple[int, ...],
    source_start: int,
    source_end: int,
) -> str:
    """Read exact XML text for a mapped range.

    Args:
        snapshot: Document snapshot.
        block_id: Block containing the node.
        node_path: Path to the text node.
        source_start: Inclusive source offset.
        source_end: Exclusive source offset.

    Returns:
        Exact substring from the XML text or tail node.
    """
    from wenlint.feishu.projection import find_block, parse_blocks, resolve_text_target

    root = parse_blocks(snapshot.xml)
    block = find_block(root, block_id)
    node, is_tail = resolve_text_target(block, node_path)
    text = (node.tail if is_tail else node.text) or ""
    return text[source_start:source_end]


def _section_for_spans(
    snapshot: DocumentSnapshot, spans: Sequence[SourceSpan]
) -> Section | None:
    """Return a section when all spans belong to one chapter.

    Args:
        snapshot: Document snapshot.
        spans: Spans covering a finding.

    Returns:
        Unique section or ``None``.
    """
    block_ids = {span.block_id for span in spans if span.block_id}
    if len(block_ids) != 1:
        return None
    return _section_for_block(snapshot, next(iter(block_ids)))


def _section_for_block(snapshot: DocumentSnapshot, block_id: str) -> Section | None:
    """Find the unique section that owns ``block_id``.

    Args:
        snapshot: Document snapshot.
        block_id: Block id to locate.

    Returns:
        Owning section or ``None`` when missing or duplicated.
    """
    matches = [section for section in snapshot.sections if block_id in section.block_ids]
    if len(matches) != 1:
        return None
    return matches[0]


def _block_url(snapshot: DocumentSnapshot, block_id: str | None) -> str | None:
    """Build a deep link for a block when a canonical URL exists.

    Args:
        snapshot: Document snapshot.
        block_id: Target block id.

    Returns:
        Canonical URL with ``#block_id`` fragment, or ``None``.
    """
    if not block_id or not snapshot.ref.canonical_url:
        return None
    base = snapshot.ref.canonical_url.split("#", 1)[0]
    return f"{base}#{block_id}"
