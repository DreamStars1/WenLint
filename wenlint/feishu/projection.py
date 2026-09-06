"""Secure Feishu XML projection, SourceMap, and block serialization.

Rejects DTD/ENTITY payloads before parse, never resolves external entities or
URLs, and treats analysis-projection prefixes as non-writable synthetic spans.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

from wenlint.feishu.models import DocumentRef, DocumentSnapshot, Patch, SourceSpan
from wenlint.feishu.sections import build_sections

_XML_LIMIT = 20 * 1024 * 1024
_UNSAFE_MARKERS = ("<!DOCTYPE", "<!ENTITY")
_HEADING_TAGS = {f"h{i}" for i in range(1, 10)}
_INLINE_TAGS = {"b", "em", "u", "del", "span", "a", "i", "strong"}
# Nested paragraph/list-item text under callout or list containers may write back
# to the replaceable top-level block id when that id is known.
_WRITABLE_NESTED_TAGS = {"p", "li"}
_EXCLUDED_BLOCK_TAGS = {
    "pre",
    "code",
    "table",
    "grid",
    "img",
    "source",
    "whiteboard",
    "sheet",
    "bitable",
    "cite",
    "synced",
}
# Omitted entirely from the analysis projection (never scannable or writable).
_OMITTED_TAGS = {
    "title",
    "synced_reference",
    "synced_source",
    "synced-reference",
    "synced-source",
}


class XmlSafetyError(ValueError):
    """Raised when XML cannot be safely parsed or projected."""

    def __init__(self, message: str, *, kind: str = "unsafe_xml") -> None:
        """Record a stable XML safety failure kind.

        Args:
            message: Human-readable explanation without payload bodies.
            kind: Machine-stable classifier.
        """
        super().__init__(message)
        self.kind = kind


def project_xml(xml: str, ref: DocumentRef, revision_id: int) -> DocumentSnapshot:
    """Parse Feishu block XML into a projection, SourceMap, and sections.

    Args:
        xml: Raw XML fragment or document body from ``docs +fetch``.
        ref: Resolved document reference for the snapshot.
        revision_id: Document revision accompanying the XML.

    Returns:
        Immutable ``DocumentSnapshot`` ready for scanning and binding.

    Raises:
        XmlSafetyError: On size limits, DTD/ENTITY markers, or malformed XML.
    """
    if ref.document_id is None or ref.canonical_url is None:
        raise XmlSafetyError(
            "projection requires a resolved Docx document reference",
            kind="unresolved_document",
        )
    root = parse_blocks(xml)
    projection_parts: list[str] = []
    source_map: list[SourceSpan] = []
    cursor = 0
    emitted_block = False

    for block in root:
        block_parts: list[str] = []
        block_map: list[SourceSpan] = []
        _project_block(block, block_parts, block_map, 0)
        if not block_parts:
            continue
        if emitted_block:
            cursor = _append_synthetic("\n", projection_parts, source_map, cursor)
        for span in block_map:
            source_map.append(
                SourceSpan(
                    projection_start=span.projection_start + cursor,
                    projection_end=span.projection_end + cursor,
                    block_id=span.block_id,
                    node_path=span.node_path,
                    source_start=span.source_start,
                    source_end=span.source_end,
                    writable=span.writable,
                )
            )
        projection_parts.extend(block_parts)
        cursor += sum(len(part) for part in block_parts)
        emitted_block = True

    projection = "".join(projection_parts)
    sections = build_sections(root)
    return DocumentSnapshot(
        ref=ref,
        revision_id=revision_id,
        xml=xml,
        projection=projection,
        source_map=tuple(source_map),
        sections=sections,
    )


def parse_blocks(xml: str) -> Element:
    """Reject unsafe markers and parse block XML under a synthetic root.

    Args:
        xml: Raw XML body.

    Returns:
        Element whose children are top-level blocks.

    Raises:
        XmlSafetyError: On limit, unsafe constructs, or parse errors.
    """
    if len(xml.encode("utf-8")) > _XML_LIMIT:
        raise XmlSafetyError("XML exceeds the 20 MiB limit", kind="xml_limit")
    upper = xml.upper()
    for marker in _UNSAFE_MARKERS:
        if marker in upper:
            raise XmlSafetyError(
                "DTD and ENTITY declarations are not allowed",
                kind="unsafe_xml",
            )
    wrapped = f"<document>{xml}</document>"
    try:
        return ET.fromstring(wrapped)
    except ET.ParseError as exc:
        raise XmlSafetyError("XML is malformed", kind="malformed_xml") from exc


def serialize_block(snapshot: DocumentSnapshot, block_id: str) -> str:
    """Serialize one top-level block from a snapshot back to XML text.

    Args:
        snapshot: Snapshot whose XML contains the block.
        block_id: Target ``block-id`` attribute value.

    Returns:
        Exact XML string for the block element.

    Raises:
        XmlSafetyError: If the block id is missing or ambiguous.
    """
    root = parse_blocks(snapshot.xml)
    return element_to_xml(find_block(root, block_id))


def replace_node_text(snapshot: DocumentSnapshot, patch: Patch) -> str:
    """Return a block XML string after replacing one approved text range.

    Args:
        snapshot: Snapshot providing the original block tree.
        patch: Contiguous text replacement inside a single node.

    Returns:
        Serialized XML for the patched block only.

    Raises:
        XmlSafetyError: If the node path or original text does not match.
    """
    root = parse_blocks(snapshot.xml)
    cloned = copy.deepcopy(find_block(root, patch.block_id))
    node, is_tail = resolve_text_target(cloned, patch.node_path)
    text = (node.tail if is_tail else node.text) or ""
    actual = text[patch.source_start : patch.source_end]
    if actual != patch.before:
        raise XmlSafetyError(
            "patch before text does not match the XML text node",
            kind="source_mismatch",
        )
    updated = text[: patch.source_start] + patch.after + text[patch.source_end :]
    if is_tail:
        node.tail = updated
    else:
        node.text = updated
    return element_to_xml(cloned)


def find_block(root: Element, block_id: str) -> Element:
    """Return the unique top-level block with ``block_id``.

    Args:
        root: Synthetic document root.
        block_id: Target block id.

    Returns:
        Matching element.

    Raises:
        XmlSafetyError: If zero or multiple blocks match.
    """
    matches = [
        child
        for child in root
        if child.attrib.get("block-id") == block_id
        or child.attrib.get("block_id") == block_id
    ]
    if len(matches) != 1:
        raise XmlSafetyError("block id must be unique", kind="block_not_found")
    return matches[0]


def resolve_text_target(
    block: Element, node_path: tuple[int, ...]
) -> tuple[Element, bool]:
    """Resolve the element and whether the edit targets ``tail``.

    Convention:
    - ``()`` edits ``block.text`` (root text node).
    - ``(0,)`` on a childless block also edits ``block.text`` for older manifests.
    - ``(child_index, ...)`` walks element children.
    - A final ``-1`` selects the ``tail`` of the resolved child.

    Args:
        block: Block root element.
        node_path: Path recorded in SourceMap / Patch.

    Returns:
        Pair of ``(element, is_tail)``.

    Raises:
        XmlSafetyError: If the path cannot be resolved.
    """
    if not node_path:
        return block, False
    # Legacy manifests recorded root text as ``(0,)``; keep that only when the
    # block has no element children so it cannot collide with child index 0.
    if node_path == (0,) and not list(block):
        return block, False

    is_tail = node_path[-1] == -1
    walk = node_path[:-1] if is_tail else node_path
    node = block
    for index in walk:
        children = list(node)
        if index < 0 or index >= len(children):
            raise XmlSafetyError("invalid node path", kind="invalid_node_path")
        node = children[index]
    return node, is_tail


def element_to_xml(element: Element) -> str:
    """Serialize an element without an XML declaration.

    Args:
        element: Element to serialize.

    Returns:
        Unicode XML string.
    """
    return ET.tostring(element, encoding="unicode")


def local_tag(tag: str) -> str:
    """Return the local tag name without a namespace URI.

    Args:
        tag: Raw ElementTree tag.

    Returns:
        Local name in lowercase.
    """
    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    return tag.lower()


def _project_block(
    block: Element,
    parts: list[str],
    source_map: list[SourceSpan],
    cursor: int,
) -> int:
    """Append one block's projection and SourceMap entries.

    Args:
        block: Top-level block element.
        parts: Projection string fragments.
        source_map: Mutable SourceMap accumulator.
        cursor: Current projection offset.

    Returns:
        Updated projection cursor.
    """
    tag = local_tag(block.tag)
    block_id = block.attrib.get("block-id") or block.attrib.get("block_id")

    if tag in _OMITTED_TAGS or tag in _EXCLUDED_BLOCK_TAGS:
        return cursor

    if tag in _HEADING_TAGS:
        level = int(tag[1])
        cursor = _append_synthetic("#" * level + " ", parts, source_map, cursor)
        # Headings stay in chapter context but are never auto-writable (§10.2).
        return _project_element(block, block_id, parts, source_map, cursor, False, ())

    if tag in {"ol", "ul"}:
        return _project_list(block, block_id, parts, source_map, cursor, tag)

    if tag in {"li", "checkbox"}:
        cursor = _append_synthetic("- ", parts, source_map, cursor)
        return _project_element(block, block_id, parts, source_map, cursor, True, ())

    if tag == "blockquote":
        cursor = _append_synthetic("> ", parts, source_map, cursor)
        return _project_element(block, block_id, parts, source_map, cursor, True, ())

    if tag in {"p", "callout"}:
        return _project_element(block, block_id, parts, source_map, cursor, True, ())

    return _project_element(block, block_id, parts, source_map, cursor, False, ())


def _project_list(
    block: Element,
    block_id: str | None,
    parts: list[str],
    source_map: list[SourceSpan],
    cursor: int,
    list_tag: str,
) -> int:
    """Project a top-level ordered or unordered list container.

    List markers and item separators are synthetic. Item text maps to the
    replaceable top-level list ``block_id`` when present; otherwise the shape
    remains scannable but non-writable.

    Args:
        block: ``ol`` or ``ul`` element.
        block_id: Top-level list block id when Feishu provided one.
        parts: Projection fragments.
        source_map: SourceMap accumulator.
        cursor: Current projection offset.
        list_tag: Normalized ``ol`` or ``ul``.

    Returns:
        Updated projection cursor.
    """
    writable = block_id is not None
    item_number = 0
    emitted_item = False
    for index, child in enumerate(block):
        child_tag = local_tag(child.tag)
        child_path = (index,)
        if child_tag != "li":
            # Unsupported siblings stay visible for diagnostics but never writable.
            cursor = _project_element(
                child,
                block_id,
                parts,
                source_map,
                cursor,
                False,
                child_path,
            )
            continue
        if emitted_item:
            cursor = _append_synthetic("\n", parts, source_map, cursor)
        item_number += 1
        marker = f"{item_number}. " if list_tag == "ol" else "- "
        cursor = _append_synthetic(marker, parts, source_map, cursor)
        cursor = _project_element(
            child,
            block_id,
            parts,
            source_map,
            cursor,
            writable,
            child_path,
        )
        emitted_item = True
    return cursor


def _project_element(
    element: Element,
    block_id: str | None,
    parts: list[str],
    source_map: list[SourceSpan],
    cursor: int,
    writable: bool,
    path: tuple[int, ...],
) -> int:
    """Project an element's text, inline children, and tails.

    Args:
        element: Current element.
        block_id: Owning block id when known.
        parts: Projection fragments.
        source_map: SourceMap accumulator.
        cursor: Current projection offset.
        writable: Whether the owning context allows writeback.
        path: Path from the block root to ``element``.

    Returns:
        Updated projection cursor.
    """
    # Root text uses ``()`` so it never collides with child index ``0``.
    if element.text:
        # Link URLs never appear as element.text of <a>; href stays in attrib.
        cursor = _append_text(
            element.text,
            block_id,
            path,
            0,
            parts,
            source_map,
            cursor,
            writable,
        )

    for index, child in enumerate(element):
        child_path = path + (index,)
        child_tag = local_tag(child.tag)
        if child_tag in _OMITTED_TAGS:
            # Resource/metadata subtrees never enter the projection; preserve
            # any trailing text owned by the parent via child.tail below.
            pass
        elif child_tag == "br":
            cursor = _append_synthetic("\n", parts, source_map, cursor)
        elif child_tag == "a":
            if child.text:
                cursor = _append_text(
                    child.text,
                    block_id,
                    child_path,
                    0,
                    parts,
                    source_map,
                    cursor,
                    writable,
                )
            for nested_index, nested in enumerate(child):
                cursor = _project_element(
                    nested,
                    block_id,
                    parts,
                    source_map,
                    cursor,
                    writable,
                    child_path + (nested_index,),
                )
                if nested.tail:
                    cursor = _append_text(
                        nested.tail,
                        block_id,
                        child_path + (nested_index, -1),
                        0,
                        parts,
                        source_map,
                        cursor,
                        writable,
                    )
        elif child_tag in _INLINE_TAGS:
            cursor = _project_element(
                child,
                block_id,
                parts,
                source_map,
                cursor,
                writable,
                child_path,
            )
        elif child_tag in _WRITABLE_NESTED_TAGS and writable:
            cursor = _project_element(
                child,
                block_id,
                parts,
                source_map,
                cursor,
                True,
                child_path,
            )
        elif child_tag in _EXCLUDED_BLOCK_TAGS:
            # Keep excluded inline resources (e.g. cite) visible for binding
            # diagnostics, but never mark them writable.
            cursor = _project_element(
                child,
                block_id,
                parts,
                source_map,
                cursor,
                False,
                child_path,
            )
        else:
            cursor = _project_element(
                child,
                block_id,
                parts,
                source_map,
                cursor,
                False,
                child_path,
            )
        if child.tail:
            cursor = _append_text(
                child.tail,
                block_id,
                child_path + (-1,),
                0,
                parts,
                source_map,
                cursor,
                writable,
            )
    return cursor


def _append_text(
    text: str,
    block_id: str | None,
    node_path: tuple[int, ...],
    source_start: int,
    parts: list[str],
    source_map: list[SourceSpan],
    cursor: int,
    writable: bool,
) -> int:
    """Append real XML text characters with one SourceSpan per run.

    Args:
        text: Exact XML text characters (no Unicode normalization).
        block_id: Owning block id when available.
        node_path: Path to the text-bearing node.
        source_start: Starting offset inside the XML text node.
        parts: Projection fragments.
        source_map: SourceMap accumulator.
        cursor: Current projection offset.
        writable: Whether automatic writeback may target these characters.

    Returns:
        Updated projection cursor.
    """
    if not text:
        return cursor
    end = cursor + len(text)
    parts.append(text)
    source_map.append(
        SourceSpan(
            projection_start=cursor,
            projection_end=end,
            block_id=block_id,
            node_path=node_path,
            source_start=source_start,
            source_end=source_start + len(text),
            writable=bool(writable and block_id is not None),
        )
    )
    return end


def _append_synthetic(
    text: str,
    parts: list[str],
    source_map: list[SourceSpan],
    cursor: int,
) -> int:
    """Append scanner-only prefix/separator characters.

    Args:
        text: Synthetic characters such as ``# `` or newlines.
        parts: Projection fragments.
        source_map: SourceMap accumulator.
        cursor: Current projection offset.

    Returns:
        Updated projection cursor.
    """
    if not text:
        return cursor
    end = cursor + len(text)
    parts.append(text)
    source_map.append(
        SourceSpan(
            projection_start=cursor,
            projection_end=end,
            block_id=None,
            node_path=None,
            source_start=0,
            source_end=0,
            writable=False,
        )
    )
    return end
