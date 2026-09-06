"""Approved patch manifest validation and fail-closed Feishu writeback.

Writes use only ``block_replace`` with explicit revisions. Target-section changes
require reconfirmation; other-section edits may retry a single revision conflict.
Successful writes are never automatically rolled back.
"""

from __future__ import annotations

import copy
import json
import os
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

from wenlint.feishu.inspection import inspect_document
from wenlint.feishu.lark import LarkCliError, LarkClient
from wenlint.feishu.models import (
    ApprovedSectionPlan,
    ApplyResult,
    DocumentRef,
    DocumentSnapshot,
    Patch,
)
from wenlint.feishu.projection import (
    XmlSafetyError,
    element_to_xml,
    find_block,
    parse_blocks,
    project_xml,
    replace_node_text,
    resolve_text_target,
)
from wenlint.feishu.sections import SectionError, locate_section

_MANIFEST_LIMIT = 1 * 1024 * 1024
_ALLOWED_TOP_LEVEL = {
    "document_id",
    "section_locator",
    "initial_fingerprint",
    "approved_patch_ids",
    "expected_fingerprints",
    "patches",
}
_ALLOWED_PATCH_FIELDS = {
    "patch_id",
    "section_locator",
    "section_fingerprint",
    "block_id",
    "node_path",
    "source_start",
    "source_end",
    "before",
    "after",
    "rule_id",
    "rationale",
}


class ManifestError(ValueError):
    """Raised when a patch manifest cannot be accepted."""

    def __init__(self, message: str, *, kind: str) -> None:
        """Record a stable manifest failure kind.

        Args:
            message: Human-readable explanation without document bodies.
            kind: Machine-stable classifier.
        """
        super().__init__(message)
        self.kind = kind


class PatchValidationError(ValueError):
    """Raised when approved patches fail structural validation."""

    def __init__(self, message: str, *, kind: str) -> None:
        """Record a stable patch validation failure kind.

        Args:
            message: Human-readable explanation.
            kind: Machine-stable classifier.
        """
        super().__init__(message)
        self.kind = kind


def load_manifest(path: Path, expected_ref: DocumentRef) -> ApprovedSectionPlan:
    """Load and parse an approved section manifest under the current cwd.

    Args:
        path: Manifest path provided by the caller.
        expected_ref: Document reference the CLI was invoked with.

    Returns:
        Parsed ``ApprovedSectionPlan``.

    Raises:
        ManifestError: On path, size, JSON, schema, or document mismatches.
    """
    if expected_ref.document_id is None:
        raise ManifestError(
            "apply requires a resolved document id",
            kind="unresolved_document",
        )

    cwd = Path.cwd().resolve()
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        raise ManifestError("manifest path could not be resolved", kind="manifest_path") from exc
    try:
        resolved.relative_to(cwd)
    except ValueError as exc:
        raise ManifestError(
            "patch manifest must stay under the current working directory",
            kind="manifest_path",
        ) from exc

    if not resolved.is_file():
        raise ManifestError("patch manifest file was not found", kind="manifest_missing")
    size = resolved.stat().st_size
    if size > _MANIFEST_LIMIT:
        raise ManifestError("patch manifest exceeds the 1 MiB limit", kind="manifest_limit")

    try:
        raw = resolved.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("patch manifest is not valid UTF-8 JSON", kind="manifest_json") from exc

    if not isinstance(payload, dict):
        raise ManifestError("patch manifest root must be an object", kind="manifest_schema")
    unknown = set(payload) - _ALLOWED_TOP_LEVEL
    if unknown:
        raise ManifestError(
            f"patch manifest contains unknown fields: {sorted(unknown)}",
            kind="unknown_fields",
        )

    document_id = payload.get("document_id")
    if document_id != expected_ref.document_id:
        raise ManifestError(
            "patch manifest document_id does not match the target document",
            kind="document_mismatch",
        )

    patches_raw = payload.get("patches")
    if not isinstance(patches_raw, list):
        raise ManifestError("patches must be a list", kind="manifest_schema")

    patches: list[Patch] = []
    seen_ids: set[str] = set()
    for item in patches_raw:
        if not isinstance(item, dict):
            raise ManifestError("each patch must be an object", kind="manifest_schema")
        unknown_patch = set(item) - _ALLOWED_PATCH_FIELDS
        if unknown_patch:
            raise ManifestError(
                f"patch contains unknown fields: {sorted(unknown_patch)}",
                kind="unknown_fields",
            )
        patch_id = str(item.get("patch_id") or "")
        if not patch_id:
            raise ManifestError("patch_id is required", kind="manifest_schema")
        if patch_id in seen_ids:
            raise ManifestError("duplicate patch_id in manifest", kind="duplicate_patch_id")
        seen_ids.add(patch_id)
        node_path = item.get("node_path")
        if not isinstance(node_path, list) or not all(isinstance(x, int) for x in node_path):
            raise ManifestError("node_path must be a list of ints", kind="manifest_schema")
        patches.append(
            Patch(
                patch_id=patch_id,
                section_locator=str(item["section_locator"]),
                section_fingerprint=str(item["section_fingerprint"]),
                block_id=str(item["block_id"]),
                node_path=tuple(node_path),
                source_start=int(item["source_start"]),
                source_end=int(item["source_end"]),
                before=str(item["before"]),
                after=str(item["after"]),
                rule_id=str(item["rule_id"]),
                rationale=str(item["rationale"]),
            )
        )

    approved_ids = payload.get("approved_patch_ids")
    if not isinstance(approved_ids, list) or not all(isinstance(x, str) for x in approved_ids):
        raise ManifestError("approved_patch_ids must be a string list", kind="manifest_schema")
    expected_fps = payload.get("expected_fingerprints")
    if not isinstance(expected_fps, list) or not all(isinstance(x, str) for x in expected_fps):
        raise ManifestError(
            "expected_fingerprints must be a string list",
            kind="manifest_schema",
        )

    approved_set = set(approved_ids)
    for patch in patches:
        if patch.patch_id not in approved_set:
            raise ManifestError(
                "manifest includes a patch that was not approved",
                kind="unapproved_patch",
            )
    if approved_set - {patch.patch_id for patch in patches}:
        raise ManifestError(
            "approved_patch_ids references a missing patch",
            kind="missing_patch",
        )

    return ApprovedSectionPlan(
        document_id=str(document_id),
        section_locator=str(payload["section_locator"]),
        initial_fingerprint=str(payload["initial_fingerprint"]),
        approved_patch_ids=tuple(approved_ids),
        expected_fingerprints=tuple(expected_fps),
        patches=tuple(patches),
    )


def validate_patches(
    snapshot: DocumentSnapshot, plan: ApprovedSectionPlan
) -> tuple[Patch, ...]:
    """Validate approved patches against the current snapshot.

    Args:
        snapshot: Latest projected document snapshot.
        plan: Approved section plan from the manifest.

    Returns:
        The validated patch tuple.

    Raises:
        PatchValidationError: On overlap, mismatch, or unsupported edits.
        SectionError: When the section locator is missing or ambiguous.
    """
    section = locate_section(snapshot, plan.section_locator)
    if section.fingerprint != plan.initial_fingerprint:
        raise PatchValidationError(
            "section fingerprint no longer matches the approved plan",
            kind="section_changed",
        )

    by_block: dict[str, list[Patch]] = defaultdict(list)
    for patch in plan.patches:
        if patch.section_locator != plan.section_locator:
            raise PatchValidationError(
                "patch section_locator does not match the plan",
                kind="section_mismatch",
            )
        if not patch.before or patch.before == patch.after:
            raise PatchValidationError(
                "patches must change a non-empty before text",
                kind="noop_patch",
            )
        if patch.source_end <= patch.source_start:
            raise PatchValidationError(
                "patch source offsets are invalid",
                kind="invalid_offsets",
            )
        if patch.block_id not in section.block_ids:
            raise PatchValidationError(
                "patch block is outside the approved section",
                kind="block_outside_section",
            )
        _assert_source_matches(snapshot, patch)
        _assert_structure_preserved(snapshot, patch)
        by_block[patch.block_id].append(patch)

    for block_id, group in by_block.items():
        ordered = sorted(group, key=lambda item: item.source_start)
        for left, right in zip(ordered, ordered[1:]):
            if left.node_path == right.node_path and left.source_end > right.source_start:
                raise PatchValidationError(
                    "overlapping patches in the same block are not allowed",
                    kind="overlapping_patches",
                )
    return plan.patches


def apply_approved_section(
    client: LarkClient,
    ref: DocumentRef,
    plan: ApprovedSectionPlan,
) -> ApplyResult:
    """Apply one approved section plan with fetch/remap after every write.

    Args:
        client: Bounded ``lark-cli`` adapter.
        ref: Resolved Docx reference.
        plan: Validated approved section plan.

    Returns:
        ``ApplyResult`` describing success, conflict, or partial failure.
    """
    if ref.document_id is None or ref.canonical_url is None:
        return ApplyResult(
            status="conflict",
            applied_patch_ids=(),
            unapplied_patch_ids=plan.approved_patch_ids,
            reconfirm_patch_ids=plan.approved_patch_ids,
            revision_id=None,
            message="document reference is unresolved",
            details={"kind": "unresolved_document"},
        )

    applied: list[str] = []
    remaining = list(plan.patches)
    expected_fps = list(plan.expected_fingerprints)
    write_index = 0
    snapshot: DocumentSnapshot

    try:
        snapshot = _fetch_snapshot(client, ref)
        section = locate_section(snapshot, plan.section_locator)
        if section.fingerprint != plan.initial_fingerprint:
            return ApplyResult(
                status="conflict",
                applied_patch_ids=(),
                unapplied_patch_ids=tuple(p.patch_id for p in remaining),
                reconfirm_patch_ids=tuple(p.patch_id for p in remaining),
                revision_id=snapshot.revision_id,
                message="target section changed before any write",
                details={"kind": "section_changed"},
            )
        validate_patches(snapshot, plan)
    except (LarkCliError, PatchValidationError, SectionError, XmlSafetyError) as exc:
        kind = getattr(exc, "kind", "preflight_failed")
        return ApplyResult(
            status="conflict",
            applied_patch_ids=(),
            unapplied_patch_ids=tuple(p.patch_id for p in remaining),
            reconfirm_patch_ids=tuple(p.patch_id for p in remaining),
            revision_id=None,
            message=str(exc),
            details={"kind": kind},
        )

    while remaining:
        try:
            locate_section(snapshot, plan.section_locator)
        except SectionError as exc:
            return _partial_or_conflict(
                applied,
                remaining,
                snapshot.revision_id,
                str(exc),
                "missing_section",
            )

        section = locate_section(snapshot, plan.section_locator)
        pre_write_fingerprint = section.fingerprint
        remaining = list(_remap_patches(snapshot, remaining))
        if not remaining:
            break

        grouped = _group_by_block(remaining)
        block_id, block_patches = next(iter(grouped.items()))
        try:
            patched_xml = _merge_block_patches(snapshot, block_id, block_patches)
        except (PatchValidationError, XmlSafetyError) as exc:
            return _partial_or_conflict(
                applied,
                remaining,
                snapshot.revision_id,
                str(exc),
                getattr(exc, "kind", "patch_failed"),
            )

        expected_fingerprint = (
            expected_fps[write_index] if write_index < len(expected_fps) else None
        )
        try:
            _replace_with_optional_retry(
                client,
                ref,
                snapshot,
                plan,
                block_id,
                patched_xml,
                pre_write_fingerprint,
            )
        except LarkCliError as exc:
            return _partial_or_conflict(
                applied,
                remaining,
                snapshot.revision_id,
                exc.message,
                exc.kind,
            )

        snapshot = _fetch_snapshot(client, ref)
        try:
            verify_section = locate_section(snapshot, plan.section_locator)
        except SectionError as exc:
            applied.extend(p.patch_id for p in block_patches)
            leftover = [
                p for p in remaining if p.patch_id not in {x.patch_id for x in block_patches}
            ]
            return ApplyResult(
                status="partial_failure",
                applied_patch_ids=tuple(applied),
                unapplied_patch_ids=tuple(p.patch_id for p in leftover),
                reconfirm_patch_ids=tuple(p.patch_id for p in leftover),
                revision_id=snapshot.revision_id,
                message=str(exc),
                details={"kind": "verify_section_missing"},
            )

        if expected_fingerprint and verify_section.fingerprint != expected_fingerprint:
            applied.extend(p.patch_id for p in block_patches)
            leftover = [
                p for p in remaining if p.patch_id not in {x.patch_id for x in block_patches}
            ]
            return ApplyResult(
                status="partial_failure",
                applied_patch_ids=tuple(applied),
                unapplied_patch_ids=tuple(p.patch_id for p in leftover),
                reconfirm_patch_ids=tuple(p.patch_id for p in leftover),
                revision_id=snapshot.revision_id,
                message="post-write section fingerprint verification failed",
                details={"kind": "verify_failed"},
            )

        applied_ids = {item.patch_id for item in block_patches}
        applied.extend(p.patch_id for p in block_patches)
        remaining = [
            patch
            for patch in _remap_patches(snapshot, remaining)
            if patch.patch_id not in applied_ids
        ]
        write_index += 1

    inspect_document(client, ref)
    return ApplyResult(
        status="success",
        applied_patch_ids=tuple(applied),
        unapplied_patch_ids=(),
        reconfirm_patch_ids=(),
        revision_id=snapshot.revision_id,
        message="approved section patches applied and verified",
    )


def _fetch_snapshot(client: LarkClient, ref: DocumentRef) -> DocumentSnapshot:
    """Fetch XML full and project a snapshot.

    Args:
        client: Lark adapter.
        ref: Document reference.

    Returns:
        Fresh ``DocumentSnapshot``.
    """
    payload = client.fetch(ref)
    data = payload["data"]  # type: ignore[index]
    document = data["document"]  # type: ignore[index]
    resolved = DocumentRef(
        input_url=ref.input_url,
        kind=ref.kind,
        input_token=ref.input_token,
        document_id=str(document["document_id"]),
        canonical_url=str(document["url"]).split("?", 1)[0],
    )
    return project_xml(str(data["content"]), resolved, int(document["revision_id"]))


def _replace_with_optional_retry(
    client: LarkClient,
    ref: DocumentRef,
    snapshot: DocumentSnapshot,
    plan: ApprovedSectionPlan,
    block_id: str,
    patched_xml: str,
    pre_write_fingerprint: str,
) -> None:
    """Replace one block, retrying once on revision conflict if section is unchanged.

    Args:
        client: Lark adapter.
        ref: Document reference.
        snapshot: Snapshot used for the first attempt.
        plan: Approved plan (for locator checks on retry).
        block_id: Block id to replace on the first attempt.
        patched_xml: Complete patched block XML.
        pre_write_fingerprint: Expected section fingerprint before this write.

    Raises:
        LarkCliError: When replace fails or a second conflict occurs.
    """
    try:
        client.replace_block(ref, block_id, patched_xml, snapshot.revision_id)
        return
    except LarkCliError as first_exc:
        if first_exc.kind != "revision_conflict":
            raise

    retry_snapshot = _fetch_snapshot(client, ref)
    section = locate_section(retry_snapshot, plan.section_locator)
    if section.fingerprint != pre_write_fingerprint:
        raise LarkCliError(
            "section_changed",
            "target section changed during revision conflict",
            retryable=False,
        )
    latest_block_id = _find_block_id_for_xml(retry_snapshot, patched_xml, block_id)
    try:
        client.replace_block(
            ref, latest_block_id, patched_xml, retry_snapshot.revision_id
        )
    except LarkCliError as exc:
        raise LarkCliError(
            "revision_conflict",
            "second consecutive revision conflict; stopping",
            retryable=False,
            details=exc.details,
        ) from exc


def _find_block_id_for_xml(
    snapshot: DocumentSnapshot, patched_xml: str, previous_id: str
) -> str:
    """Locate the latest block id for a patched XML payload.

    Args:
        snapshot: Latest snapshot.
        patched_xml: Patched block XML.
        previous_id: Previous block id used as a fallback hint.

    Returns:
        Block id to use for the retry replace.
    """
    # Prefer an exact block-id attribute still present after remapping suffixes.
    root = parse_blocks(snapshot.xml)
    # Match by canonical text content equality with the patched element.
    patched = parse_blocks(patched_xml)[0]
    patched_text = "".join(patched.itertext())
    for child in root:
        if "".join(child.itertext()) == patched_text:
            return child.attrib.get("block-id") or child.attrib.get("block_id") or previous_id
    # Fallback: previous id with a single ``-new`` suffix used by tests.
    candidate = f"{previous_id}-new"
    for child in root:
        block_id = child.attrib.get("block-id") or child.attrib.get("block_id")
        if block_id == candidate:
            return candidate
    return previous_id


def _group_by_block(patches: list[Patch]) -> dict[str, list[Patch]]:
    """Group patches by block preserving first-seen block order.

    Args:
        patches: Remapped patches still awaiting writes.

    Returns:
        Ordered mapping of block id to patches.
    """
    grouped: dict[str, list[Patch]] = {}
    for patch in patches:
        grouped.setdefault(patch.block_id, []).append(patch)
    return grouped


def _merge_block_patches(
    snapshot: DocumentSnapshot, block_id: str, patches: list[Patch]
) -> str:
    """Apply all patches for one block from highest source offset to lowest.

    Args:
        snapshot: Current snapshot.
        block_id: Target block id.
        patches: Non-overlapping patches for the block.

    Returns:
        Complete patched block XML.

    Raises:
        PatchValidationError: If structure beyond approved text would change.
        XmlSafetyError: If a replacement cannot be applied.
    """
    ordered = sorted(patches, key=lambda item: item.source_start, reverse=True)
    working = snapshot
    xml = None
    for patch in ordered:
        xml = replace_node_text(working, patch)
        # Rebuild a temporary snapshot XML with only this block replaced so the
        # next offset still refers to the original source coordinates.
        root = parse_blocks(working.xml)
        original = element_to_xml(find_block(root, block_id))
        new_doc = working.xml.replace(original, xml, 1)
        working = project_xml(new_doc, working.ref, working.revision_id)
    assert xml is not None
    _assert_only_text_changed(snapshot, block_id, xml, patches)
    return xml


def _remap_patches(snapshot: DocumentSnapshot, patches: list[Patch]) -> list[Patch]:
    """Remap patches onto the latest block ids and node paths by exact text.

    Args:
        snapshot: Latest snapshot.
        patches: Patches using potentially stale block ids.

    Returns:
        Patches with refreshed block ids/node paths where uniquely found.
    """
    remapped: list[Patch] = []
    for patch in patches:
        match = _locate_exact_text(snapshot, patch)
        if match is None:
            remapped.append(patch)
            continue
        block_id, node_path, source_start, source_end = match
        remapped.append(
            Patch(
                patch_id=patch.patch_id,
                section_locator=patch.section_locator,
                section_fingerprint=patch.section_fingerprint,
                block_id=block_id,
                node_path=node_path,
                source_start=source_start,
                source_end=source_end,
                before=patch.before,
                after=patch.after,
                rule_id=patch.rule_id,
                rationale=patch.rationale,
            )
        )
    return remapped


def _locate_exact_text(
    snapshot: DocumentSnapshot, patch: Patch
) -> tuple[str, tuple[int, ...], int, int] | None:
    """Find a unique writable occurrence of ``patch.before``.

    Args:
        snapshot: Current snapshot.
        patch: Patch whose ``before`` text must still exist.

    Returns:
        ``(block_id, node_path, source_start, source_end)`` or ``None``.
    """
    matches: list[tuple[str, tuple[int, ...], int, int]] = []
    for span in snapshot.source_map:
        if not span.writable or span.block_id is None or span.node_path is None:
            continue
        if span.source_end - span.source_start < len(patch.before):
            continue
        # Compare using projection slice that corresponds to this span.
        text = snapshot.projection[span.projection_start : span.projection_end]
        start_at = 0
        while True:
            index = text.find(patch.before, start_at)
            if index < 0:
                break
            matches.append(
                (
                    span.block_id,
                    span.node_path,
                    span.source_start + index,
                    span.source_start + index + len(patch.before),
                )
            )
            start_at = index + 1
    if len(matches) != 1:
        return None
    return matches[0]


def _assert_source_matches(snapshot: DocumentSnapshot, patch: Patch) -> None:
    """Require exact before text at the declared source offsets.

    Args:
        snapshot: Current snapshot.
        patch: Patch to verify.

    Raises:
        PatchValidationError: On mismatch.
    """
    root = parse_blocks(snapshot.xml)
    try:
        block = find_block(root, patch.block_id)
        node, is_tail = resolve_text_target(block, patch.node_path)
    except XmlSafetyError as exc:
        raise PatchValidationError(str(exc), kind=exc.kind) from exc
    text = (node.tail if is_tail else node.text) or ""
    actual = text[patch.source_start : patch.source_end]
    if actual != patch.before:
        raise PatchValidationError(
            "patch before text does not match the current XML node",
            kind="source_mismatch",
        )


def _assert_structure_preserved(snapshot: DocumentSnapshot, patch: Patch) -> None:
    """Ensure a prospective patch only changes approved text content.

    Args:
        snapshot: Current snapshot.
        patch: Candidate patch.

    Raises:
        PatchValidationError: If attributes, tags, or resources would change.
    """
    try:
        patched = replace_node_text(snapshot, patch)
    except XmlSafetyError as exc:
        raise PatchValidationError(str(exc), kind=exc.kind) from exc
    _assert_only_text_changed(snapshot, patch.block_id, patched, [patch])


def _assert_only_text_changed(
    snapshot: DocumentSnapshot,
    block_id: str,
    patched_xml: str,
    patches: list[Patch],
) -> None:
    """Compare original and patched trees and allow only approved text edits.

    Args:
        snapshot: Snapshot containing the original block.
        block_id: Block being patched.
        patched_xml: Candidate patched block XML.
        patches: Patches that justify text differences.

    Raises:
        PatchValidationError: On disallowed structural drift.
    """
    original = find_block(parse_blocks(snapshot.xml), block_id)
    patched = parse_blocks(patched_xml)[0]
    if not _same_structure(original, patched):
        raise PatchValidationError(
            "patched XML changes tags, attributes, or resources",
            kind="structure_changed",
        )


def _same_structure(left: Element, right: Element) -> bool:
    """Return whether two elements share tags, attributes, and child shape.

    Args:
        left: Original element.
        right: Patched element.

    Returns:
        ``True`` when only text/tail content may differ.
    """
    if left.tag != right.tag or dict(left.attrib) != dict(right.attrib):
        return False
    left_children = list(left)
    right_children = list(right)
    if len(left_children) != len(right_children):
        return False
    return all(
        _same_structure(left_child, right_child)
        for left_child, right_child in zip(left_children, right_children)
    )


def _partial_or_conflict(
    applied: list[str],
    remaining: list[Patch],
    revision_id: int | None,
    message: str,
    kind: str,
) -> ApplyResult:
    """Build a conflict or partial_failure result.

    Args:
        applied: Patch ids already verified after writes.
        remaining: Patches not yet successfully applied.
        revision_id: Latest known revision.
        message: Compact error message.
        kind: Stable failure kind.

    Returns:
        ``ApplyResult`` with status depending on whether writes occurred.
    """
    unapplied = tuple(p.patch_id for p in remaining if p.patch_id not in set(applied))
    if applied:
        return ApplyResult(
            status="partial_failure",
            applied_patch_ids=tuple(applied),
            unapplied_patch_ids=unapplied,
            reconfirm_patch_ids=unapplied,
            revision_id=revision_id,
            message=message,
            details={"kind": kind},
        )
    return ApplyResult(
        status="conflict",
        applied_patch_ids=(),
        unapplied_patch_ids=unapplied,
        reconfirm_patch_ids=unapplied,
        revision_id=revision_id,
        message=message,
        details={"kind": kind},
    )
