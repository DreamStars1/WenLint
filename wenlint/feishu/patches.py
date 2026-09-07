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

from wenlint.feishu.document import DocumentRefError, resolve_fetched_docx_ref
from wenlint.feishu.findings import bind_findings
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
from wenlint.feishu.sections import SectionError, locate_section, owning_section
from wenlint.scanner import scan_text

_MANIFEST_LIMIT = 1 * 1024 * 1024
_ALLOWED_TOP_LEVEL = {
    "document_id",
    "section_locator",
    "initial_fingerprint",
    "base_revision",
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
        required = (
            "section_locator",
            "section_fingerprint",
            "block_id",
            "source_start",
            "source_end",
            "before",
            "after",
            "rule_id",
            "rationale",
        )
        missing = [key for key in required if key not in item]
        if missing:
            raise ManifestError(
                f"patch is missing required fields: {missing}",
                kind="manifest_schema",
            )
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
    if len(approved_ids) != len(set(approved_ids)):
        raise ManifestError(
            "approved_patch_ids must not contain duplicates",
            kind="duplicate_approved_id",
        )
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

    for key in ("section_locator", "initial_fingerprint"):
        if key not in payload or not isinstance(payload[key], str) or not payload[key]:
            raise ManifestError(
                f"manifest field {key} is required",
                kind="manifest_schema",
            )
    base_revision = payload.get("base_revision")
    if not isinstance(base_revision, int) or isinstance(base_revision, bool) or base_revision < 0:
        raise ManifestError(
            "manifest field base_revision must be a non-negative integer",
            kind="manifest_schema",
        )

    return ApprovedSectionPlan(
        document_id=str(document_id),
        section_locator=str(payload["section_locator"]),
        initial_fingerprint=str(payload["initial_fingerprint"]),
        base_revision=base_revision,
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
        PatchValidationError: On overlap, mismatch, unsupported edits, or when
            a patch targets a block whose writeback owner is not the approved
            section (deepest hierarchical owner via ``owning_section``).
        SectionError: When the section locator is missing or ambiguous.
    """
    section = locate_section(snapshot, plan.section_locator)
    if section.fingerprint != plan.initial_fingerprint:
        raise PatchValidationError(
            "section fingerprint no longer matches the approved plan",
            kind="section_changed",
        )

    bound = _bound_findings_for_snapshot(snapshot)
    by_block: dict[str, list[Patch]] = defaultdict(list)
    block_order: list[str] = []
    for patch in plan.patches:
        if patch.section_locator != plan.section_locator:
            raise PatchValidationError(
                "patch section_locator does not match the plan",
                kind="section_mismatch",
            )
        if patch.section_fingerprint != plan.initial_fingerprint:
            raise PatchValidationError(
                "patch section_fingerprint does not match the approved plan",
                kind="fingerprint_mismatch",
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
        try:
            owner = owning_section(snapshot, patch.block_id)
        except SectionError as exc:
            raise PatchValidationError(
                "patch block is outside the approved section",
                kind="block_outside_section",
            ) from exc
        if owner.locator != plan.section_locator:
            raise PatchValidationError(
                "patch block is outside the approved section",
                kind="block_outside_section",
            )
        _assert_source_matches(snapshot, patch)
        _assert_writable_source(snapshot, patch)
        _assert_patch_bound_to_finding(bound, patch)
        _assert_structure_preserved(snapshot, patch)
        if patch.block_id not in by_block:
            block_order.append(patch.block_id)
        by_block[patch.block_id].append(patch)

    for block_id, group in by_block.items():
        ordered = sorted(group, key=lambda item: item.source_start)
        for left, right in zip(ordered, ordered[1:]):
            if left.node_path == right.node_path and left.source_end > right.source_start:
                raise PatchValidationError(
                    "overlapping patches in the same block are not allowed",
                    kind="overlapping_patches",
                )

    if len(plan.expected_fingerprints) != len(block_order):
        raise PatchValidationError(
            "expected_fingerprints must match the number of block write groups",
            kind="expected_fingerprints_mismatch",
        )
    if any(not fingerprint for fingerprint in plan.expected_fingerprints):
        raise PatchValidationError(
            "expected_fingerprints entries must be non-empty",
            kind="expected_fingerprints_mismatch",
        )
    derived = _derive_expected_fingerprints(snapshot, block_order, by_block)
    if tuple(plan.expected_fingerprints) != tuple(derived):
        raise PatchValidationError(
            "expected_fingerprints do not match the derived post-write fingerprints",
            kind="expected_fingerprint_mismatch",
        )
    return plan.patches


def _bound_findings_for_snapshot(snapshot: DocumentSnapshot):
    """Re-scan and bind findings for the current snapshot.

    Args:
        snapshot: Document snapshot to scan.

    Returns:
        Bound findings used to authenticate approved patches.
    """
    public = []
    for item in scan_text(snapshot.projection):
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
    return bind_findings(snapshot, public)


def _assert_writable_source(snapshot: DocumentSnapshot, patch: Patch) -> None:
    """Require the patched source range to sit on writable SourceMap spans.

    Args:
        snapshot: Current snapshot.
        patch: Candidate patch.

    Raises:
        PatchValidationError: When the range is missing or not writable.
    """
    spans = [
        span
        for span in snapshot.source_map
        if span.block_id == patch.block_id
        and span.node_path == patch.node_path
        and span.source_end > patch.source_start
        and span.source_start < patch.source_end
    ]
    if not spans or any(not span.writable for span in spans):
        raise PatchValidationError(
            "patch targets an unsupported or non-writable source span",
            kind="unsupported_block",
        )


def _assert_patch_bound_to_finding(bound, patch: Patch) -> None:
    """Require each patch to match one current writable WenLint finding.

    Args:
        bound: Bound findings from the latest snapshot.
        patch: Candidate patch.

    Raises:
        PatchValidationError: When no matching writable finding exists.
    """
    for item in bound:
        loc = item.location
        if not loc.writable:
            continue
        if item.rule != patch.rule_id:
            continue
        if loc.block_id != patch.block_id:
            continue
        if loc.node_path != patch.node_path:
            continue
        if loc.source_start != patch.source_start or loc.source_end != patch.source_end:
            continue
        if str(item.finding.get("text") or "") != patch.before:
            continue
        return
    raise PatchValidationError(
        "patch is not bound to a current writable WenLint finding",
        kind="finding_mismatch",
    )


def _derive_expected_fingerprints(
    snapshot: DocumentSnapshot,
    block_order: list[str],
    by_block: dict[str, list[Patch]],
) -> list[str]:
    """Compute post-write section fingerprints for each block group.

    Args:
        snapshot: Pre-write snapshot.
        block_order: Block ids in first-seen write order.
        by_block: Patches grouped by block id.

    Returns:
        Fingerprint list aligned with ``block_order``.
    """
    working_xml = snapshot.xml
    fingerprints: list[str] = []
    section_locator = by_block[block_order[0]][0].section_locator
    for block_id in block_order:
        current = project_xml(working_xml, snapshot.ref, snapshot.revision_id)
        patched_block = _merge_block_patches(current, block_id, by_block[block_id])
        original = element_to_xml(find_block(parse_blocks(working_xml), block_id))
        if original not in working_xml:
            raise PatchValidationError(
                "unable to derive expected fingerprint for block write group",
                kind="expected_fingerprint_mismatch",
            )
        working_xml = working_xml.replace(original, patched_block, 1)
        updated = project_xml(working_xml, snapshot.ref, snapshot.revision_id)
        fingerprints.append(locate_section(updated, section_locator).fingerprint)
    return fingerprints


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

    Raises:
        PatchValidationError: For static manifest/structure invalidity that
            must surface as CLI exit 2 rather than a document conflict.
        ManifestError: Propagated for callers that load then apply.
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
    warnings: list[object] = []
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
    except LarkCliError:
        # Dependency/auth/network/protocol failures must surface as exit 3.
        raise
    except (SectionError, XmlSafetyError) as exc:
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
    except DocumentRefError as exc:
        return ApplyResult(
            status="conflict",
            applied_patch_ids=(),
            unapplied_patch_ids=tuple(p.patch_id for p in remaining),
            reconfirm_patch_ids=tuple(p.patch_id for p in remaining),
            revision_id=None,
            message=str(exc),
            details={"kind": getattr(exc, "kind", "unresolved_document")},
        )
    except PatchValidationError as exc:
        if exc.kind == "section_changed":
            return ApplyResult(
                status="conflict",
                applied_patch_ids=(),
                unapplied_patch_ids=tuple(p.patch_id for p in remaining),
                reconfirm_patch_ids=tuple(p.patch_id for p in remaining),
                revision_id=snapshot.revision_id if "snapshot" in locals() else None,
                message=str(exc),
                details={"kind": exc.kind},
            )
        # Static invalidity (overlap, noop, fingerprint count, …) → exit 2.
        raise

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
                warnings=warnings,
            )

        section = locate_section(snapshot, plan.section_locator)
        pre_write_fingerprint = section.fingerprint
        try:
            remaining = list(
                _remap_patches(snapshot, remaining, plan.section_locator)
            )
        except PatchValidationError as exc:
            return _partial_or_conflict(
                applied,
                remaining,
                snapshot.revision_id,
                str(exc),
                getattr(exc, "kind", "remap_failed"),
                warnings=warnings,
            )
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
                warnings=warnings,
            )

        if write_index >= len(expected_fps):
            return _partial_or_conflict(
                applied,
                remaining,
                snapshot.revision_id,
                "missing expected fingerprint for block write",
                "expected_fingerprints_mismatch",
                warnings=warnings,
            )
        expected_fingerprint = expected_fps[write_index]
        try:
            replace_payload = _replace_with_optional_retry(
                client,
                ref,
                snapshot,
                plan,
                block_id,
                block_patches,
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
                warnings=warnings,
            )
        except (PatchValidationError, SectionError, XmlSafetyError) as exc:
            return _partial_or_conflict(
                applied,
                remaining,
                snapshot.revision_id,
                str(exc),
                getattr(exc, "kind", "replace_failed"),
                warnings=warnings,
            )

        replace_warnings = []
        if isinstance(replace_payload, Mapping):
            top_warnings = replace_payload.get("warnings")
            if isinstance(top_warnings, list) and top_warnings:
                replace_warnings.extend(top_warnings)
            data = replace_payload.get("data")
            if isinstance(data, Mapping):
                raw_warnings = data.get("warnings") or []
                if isinstance(raw_warnings, list) and raw_warnings:
                    replace_warnings.extend(raw_warnings)
            if replace_warnings:
                warnings.extend(replace_warnings)

        try:
            snapshot = _fetch_snapshot(client, ref)
        except (LarkCliError, XmlSafetyError) as exc:
            applied.extend(p.patch_id for p in block_patches)
            leftover = [
                p for p in remaining if p.patch_id not in {x.patch_id for x in block_patches}
            ]
            return ApplyResult(
                status="partial_failure",
                applied_patch_ids=tuple(applied),
                unapplied_patch_ids=tuple(p.patch_id for p in leftover),
                reconfirm_patch_ids=tuple(p.patch_id for p in leftover),
                revision_id=None,
                message=str(getattr(exc, "message", exc)),
                details={
                    "kind": getattr(exc, "kind", "post_write_fetch_failed"),
                    "warnings": warnings,
                    "verified_after_warnings": False,
                },
            )

        try:
            verify_section = locate_section(snapshot, plan.section_locator)
            _verify_block_patches(snapshot, block_patches)
        except (SectionError, PatchValidationError, XmlSafetyError) as exc:
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
                details={
                    "kind": getattr(exc, "kind", "verify_failed"),
                    "warnings": warnings,
                    "verified_after_warnings": False,
                },
            )

        if verify_section.fingerprint != expected_fingerprint:
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
                details={
                    "kind": "verify_failed",
                    "warnings": warnings,
                    "verified_after_warnings": False,
                },
            )

        applied_ids = {item.patch_id for item in block_patches}
        applied.extend(p.patch_id for p in block_patches)
        leftover = [patch for patch in remaining if patch.patch_id not in applied_ids]
        try:
            remaining = list(
                _remap_patches(snapshot, leftover, plan.section_locator)
            )
        except PatchValidationError as exc:
            return ApplyResult(
                status="partial_failure",
                applied_patch_ids=tuple(applied),
                unapplied_patch_ids=tuple(p.patch_id for p in leftover),
                reconfirm_patch_ids=tuple(p.patch_id for p in leftover),
                revision_id=snapshot.revision_id,
                message=str(exc),
                details={
                    "kind": getattr(exc, "kind", "remap_failed"),
                    "warnings": warnings,
                    "verified_after_warnings": not bool(replace_warnings),
                },
            )
        write_index += 1

    try:
        inspect_document(client, ref)
    except (LarkCliError, XmlSafetyError, DocumentRefError) as exc:
        return ApplyResult(
            status="partial_failure",
            applied_patch_ids=tuple(applied),
            unapplied_patch_ids=(),
            reconfirm_patch_ids=(),
            revision_id=snapshot.revision_id,
            message=str(getattr(exc, "message", exc)),
            details={
                "kind": getattr(exc, "kind", "final_inspect_failed"),
                "warnings": warnings,
                "verified_after_warnings": False,
            },
        )

    return ApplyResult(
        status="success",
        applied_patch_ids=tuple(applied),
        unapplied_patch_ids=(),
        reconfirm_patch_ids=(),
        revision_id=snapshot.revision_id,
        message="approved section patches applied and verified",
        details={
            "warnings": warnings,
            "verified_after_warnings": True,
        },
    )


def _fetch_snapshot(client: LarkClient, ref: DocumentRef) -> DocumentSnapshot:
    """Fetch XML full and project a snapshot.

    Args:
        client: Lark adapter.
        ref: Document reference.

    Returns:
        Fresh ``DocumentSnapshot``.

    Raises:
        LarkCliError: When the fetch payload lacks required fields.
        XmlSafetyError: When XML projection fails.
    """
    payload = client.fetch(ref)
    data = payload.get("data") if isinstance(payload, Mapping) else None
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
    document_id = document.get("document_id")
    url = document.get("url")
    revision_id = document.get("revision_id")
    content = data.get("content")
    if not document_id or not url or revision_id is None or not isinstance(content, str):
        raise LarkCliError(
            "invalid_response",
            "fetch response is missing required document fields",
            retryable=False,
        )
    if isinstance(revision_id, bool) or not isinstance(revision_id, int):
        raise LarkCliError(
            "invalid_response",
            "fetch response revision_id must be an integer",
            retryable=False,
        )
    try:
        resolved = resolve_fetched_docx_ref(ref, str(document_id), str(url))
    except DocumentRefError as exc:
        raise LarkCliError(
            getattr(exc, "kind", "unresolved_document"),
            str(exc),
            retryable=False,
        ) from exc
    return project_xml(content, resolved, int(revision_id))


def _replace_with_optional_retry(
    client: LarkClient,
    ref: DocumentRef,
    snapshot: DocumentSnapshot,
    plan: ApprovedSectionPlan,
    block_id: str,
    block_patches: list[Patch],
    patched_xml: str,
    pre_write_fingerprint: str,
) -> Mapping[str, object]:
    """Replace one block, retrying once on revision conflict if section is unchanged.

    On retry, remaps patches structurally onto the latest snapshot and regenerates
    patched XML so stale block ids are never reused.

    Args:
        client: Lark adapter.
        ref: Document reference.
        snapshot: Snapshot used for the first attempt.
        plan: Approved plan (for locator checks on retry).
        block_id: Block id to replace on the first attempt.
        block_patches: Patches for this block write group.
        patched_xml: Complete patched block XML for the first attempt.
        pre_write_fingerprint: Expected section fingerprint before this write.

    Returns:
        Successful replace response mapping.

    Raises:
        LarkCliError: When replace fails or a second conflict occurs.
        PatchValidationError: When structural remap fails on retry.
    """
    try:
        return client.replace_block(ref, block_id, patched_xml, snapshot.revision_id)
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
    remapped = list(_remap_patches(retry_snapshot, block_patches, plan.section_locator))
    latest_block_id = remapped[0].block_id
    latest_xml = _merge_block_patches(retry_snapshot, latest_block_id, remapped)
    try:
        return client.replace_block(
            ref, latest_block_id, latest_xml, retry_snapshot.revision_id
        )
    except LarkCliError as exc:
        if exc.kind == "revision_conflict":
            raise LarkCliError(
                "revision_conflict",
                "second consecutive revision conflict; stopping",
                retryable=False,
                details=exc.details,
            ) from exc
        raise


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

    Edits mutate a deep-copied block tree in place. Document-wide XML string
    matching is forbidden so decoy identical fragments cannot be rewritten.

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
    doc = copy.deepcopy(parse_blocks(snapshot.xml))
    for patch in ordered:
        block = find_block(doc, block_id)
        try:
            node, is_tail = resolve_text_target(block, patch.node_path)
        except XmlSafetyError as exc:
            raise PatchValidationError(str(exc), kind=exc.kind) from exc
        text = (node.tail if is_tail else node.text) or ""
        if text[patch.source_start : patch.source_end] != patch.before:
            raise PatchValidationError(
                "patch before text does not match the current XML node",
                kind="source_mismatch",
            )
        new_text = text[: patch.source_start] + patch.after + text[patch.source_end :]
        if is_tail:
            node.tail = new_text
        else:
            node.text = new_text
    xml = element_to_xml(find_block(doc, block_id))
    _assert_only_text_changed(snapshot, block_id, xml, patches)
    return xml


def _remap_patches(
    snapshot: DocumentSnapshot,
    patches: list[Patch],
    section_locator: str,
) -> list[Patch]:
    """Remap patches onto latest block ids using structural section coordinates.

    Never searches by free-text occurrence. Within the target section, each patch
    must resolve uniquely via ``node_path`` plus exact ``before`` offsets.

    Args:
        snapshot: Latest snapshot.
        patches: Patches using potentially stale block ids.
        section_locator: Approved section locator.

    Returns:
        Patches with refreshed block ids.

    Raises:
        PatchValidationError: When a patch cannot be uniquely remapped, or the
            remapped block's writeback owner is not ``section_locator``.
    """
    section = locate_section(snapshot, section_locator)
    remapped: list[Patch] = []
    for patch in patches:
        candidates: list[str] = []
        for block_id in section.block_ids:
            if not block_id:
                continue
            try:
                root = parse_blocks(snapshot.xml)
                block = find_block(root, block_id)
                node, is_tail = resolve_text_target(block, patch.node_path)
            except XmlSafetyError:
                continue
            text = (node.tail if is_tail else node.text) or ""
            if text[patch.source_start : patch.source_end] != patch.before:
                continue
            candidates.append(block_id)
        if len(candidates) != 1:
            raise PatchValidationError(
                "patch could not be uniquely remapped on the latest snapshot",
                kind="remap_failed",
            )
        try:
            owner = owning_section(snapshot, candidates[0])
        except SectionError as exc:
            raise PatchValidationError(
                "remapped patch block is outside the approved section",
                kind="block_outside_section",
            ) from exc
        if owner.locator != section_locator:
            raise PatchValidationError(
                "remapped patch block is outside the approved section",
                kind="block_outside_section",
            )
        remapped.append(
            Patch(
                patch_id=patch.patch_id,
                section_locator=patch.section_locator,
                section_fingerprint=patch.section_fingerprint,
                block_id=candidates[0],
                node_path=patch.node_path,
                source_start=patch.source_start,
                source_end=patch.source_end,
                before=patch.before,
                after=patch.after,
                rule_id=patch.rule_id,
                rationale=patch.rationale,
            )
        )
    return remapped


def _verify_block_patches(snapshot: DocumentSnapshot, patches: list[Patch]) -> None:
    """Verify approved replacements are present after a successful write.

    Args:
        snapshot: Post-write snapshot.
        patches: Patches that were just written for one block group.

    Raises:
        PatchValidationError: When expected ``after`` text is missing.
    """
    for patch in patches:
        expected = Patch(
            patch_id=patch.patch_id,
            section_locator=patch.section_locator,
            section_fingerprint=patch.section_fingerprint,
            block_id=patch.block_id,
            node_path=patch.node_path,
            source_start=patch.source_start,
            source_end=patch.source_start + len(patch.after),
            before=patch.after,
            after=patch.after,
            rule_id=patch.rule_id,
            rationale=patch.rationale,
        )
        try:
            remapped = _remap_patches(snapshot, [expected], patch.section_locator)[0]
        except PatchValidationError as exc:
            raise PatchValidationError(
                "post-write block text verification failed",
                kind="verify_failed",
            ) from exc
        root = parse_blocks(snapshot.xml)
        block = find_block(root, remapped.block_id)
        node, is_tail = resolve_text_target(block, remapped.node_path)
        text = (node.tail if is_tail else node.text) or ""
        actual = text[remapped.source_start : remapped.source_end]
        if actual != patch.after:
            raise PatchValidationError(
                "post-write block text verification failed",
                kind="verify_failed",
            )


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
    *,
    warnings: list[object] | None = None,
) -> ApplyResult:
    """Build a conflict or partial_failure result.

    Args:
        applied: Patch ids already verified after writes.
        remaining: Patches not yet successfully applied.
        revision_id: Latest known revision.
        message: Compact error message.
        kind: Stable failure kind.
        warnings: Safe warning summaries collected from updates.

    Returns:
        ``ApplyResult`` with status depending on whether writes occurred.
    """
    unapplied = tuple(p.patch_id for p in remaining if p.patch_id not in set(applied))
    details: dict[str, object] = {"kind": kind}
    if warnings:
        details["warnings"] = list(warnings)
        details["verified_after_warnings"] = False
    if applied:
        return ApplyResult(
            status="partial_failure",
            applied_patch_ids=tuple(applied),
            unapplied_patch_ids=unapplied,
            reconfirm_patch_ids=unapplied,
            revision_id=revision_id,
            message=message,
            details=details,
        )
    return ApplyResult(
        status="conflict",
        applied_patch_ids=(),
        unapplied_patch_ids=unapplied,
        reconfirm_patch_ids=unapplied,
        revision_id=revision_id,
        message=message,
        details=details,
    )
