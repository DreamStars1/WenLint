"""Section boundaries, structural locators, and canonical fingerprints.

Fingerprints ignore volatile block ids and revisions so collaborators renaming
ids do not invalidate an unchanged chapter, while any text or semantic
structure change does. Canonical encoding escapes text/attrs and marks child
boundaries so literal markup characters cannot collide with real elements.
"""

from __future__ import annotations

import hashlib
from xml.etree.ElementTree import Element

from wenlint.feishu.models import DocumentSnapshot, Section
from wenlint.feishu.xml_protocol import block_id_of

_HEADING_TAGS = {f"h{i}" for i in range(1, 10)}
# Drop Feishu identity dialects and revision markers. Changing only id dialect
# or id values must not invalidate an otherwise unchanged chapter fingerprint.
_VOLATILE_ATTRS = {
    "id",
    "block-id",
    "block_id",
    "revision-id",
    "revision_id",
}
LEAD_IN_LOCATOR = "文档开头"
LEAD_IN_TITLE = "文档开头"


class SectionError(ValueError):
    """Raised when a section locator cannot be resolved uniquely."""

    def __init__(self, message: str, *, kind: str = "section_error") -> None:
        """Record a stable section lookup failure.

        Args:
            message: Human-readable explanation.
            kind: Machine-stable classifier.
        """
        super().__init__(message)
        self.kind = kind


def build_sections(root: Element) -> tuple[Section, ...]:
    """Derive ordered sections from a parsed document root.

    Args:
        root: Synthetic ``<document>`` element whose children are blocks.

    Returns:
        Frozen section tuple covering the whole document.
    """
    blocks = list(root)
    if not blocks:
        return ()

    headings: list[tuple[int, int, str, str]] = []
    for index, block in enumerate(blocks):
        tag = _local(block.tag)
        if tag in _HEADING_TAGS:
            level = int(tag[1])
            block_id = _block_id_or_empty(block)
            title = "".join(block.itertext())
            headings.append((index, level, title, block_id))

    if not headings:
        block_ids = tuple(_block_id_or_empty(block) for block in blocks)
        fingerprint = _fingerprint_elements(blocks)
        return (
            Section(
                locator=LEAD_IN_LOCATOR,
                title=LEAD_IN_TITLE,
                level=0,
                block_ids=block_ids,
                fingerprint=fingerprint,
            ),
        )

    sections: list[Section] = []
    # Content before the first heading becomes the synthetic lead-in section.
    first_heading_index = headings[0][0]
    if first_heading_index > 0:
        lead_blocks = blocks[:first_heading_index]
        sections.append(
            Section(
                locator=LEAD_IN_LOCATOR,
                title=LEAD_IN_TITLE,
                level=0,
                block_ids=tuple(_block_id_or_empty(b) for b in lead_blocks),
                fingerprint=_fingerprint_elements(lead_blocks),
            )
        )

    # Stack entries are (title, level, ordinal). Parent identity includes every
    # ancestor ordinal so duplicate titles under different parents restart at [1].
    stack: list[tuple[str, int, int]] = []
    sibling_counters: dict[tuple[tuple[str, int], ...], dict[str, int]] = {}

    for heading_pos, (start, level, title, _block_id) in enumerate(headings):
        while stack and stack[-1][1] >= level:
            stack.pop()
        parent_key = tuple((entry[0], entry[2]) for entry in stack)
        counters = sibling_counters.setdefault(parent_key, {})
        counters[title] = counters.get(title, 0) + 1
        ordinal = counters[title]
        stack.append((title, level, ordinal))
        locator = "/".join(f"{part}[{ord_}]" for part, _lvl, ord_ in stack)

        end = len(blocks)
        for later_start, later_level, _later_title, _ in headings[heading_pos + 1 :]:
            if later_level <= level:
                end = later_start
                break
        section_blocks = blocks[start:end]
        sections.append(
            Section(
                locator=locator,
                title=title,
                level=level,
                block_ids=tuple(_block_id_or_empty(b) for b in section_blocks),
                fingerprint=_fingerprint_elements(section_blocks),
            )
        )

    return tuple(sections)


def _block_id_or_empty(element: Element) -> str:
    """Return a block id string, using ``\"\"`` when absent.

    Args:
        element: Block element.

    Returns:
        Non-empty block id or an empty string placeholder for section lists.

    Raises:
        XmlProtocolError: When id attributes conflict.
    """
    value = block_id_of(element)
    return value or ""


def locate_section(snapshot: DocumentSnapshot, locator: str) -> Section:
    """Return the unique section matching ``locator``.

    Args:
        snapshot: Document snapshot containing sections.
        locator: Structural locator string.

    Returns:
        Matching ``Section``.

    Raises:
        SectionError: If zero or multiple sections share the locator.
    """
    matches = [section for section in snapshot.sections if section.locator == locator]
    if len(matches) != 1:
        raise SectionError(
            "section locator must resolve to exactly one section",
            kind="ambiguous_section" if matches else "missing_section",
        )
    return matches[0]


def owning_section(snapshot: DocumentSnapshot, block_id: str) -> Section:
    """Return the single writeback owner for ``block_id``.

    Nested headings produce overlapping ``block_ids`` ranges: a parent chapter
    includes child blocks. The writeback owner is the deepest matching
    hierarchical section (highest level, then longest locator).

    Args:
        snapshot: Document snapshot containing sections.
        block_id: Target block id.

    Returns:
        The unique deepest owning ``Section``.

    Raises:
        SectionError: If no section contains the block, or more than one
            section ties for deepest ownership (fail-closed).
    """
    matches = [section for section in snapshot.sections if block_id in section.block_ids]
    if not matches:
        raise SectionError(
            "block is not owned by any section",
            kind="missing_section",
        )
    deepest_level = max(section.level for section in matches)
    deepest = [section for section in matches if section.level == deepest_level]
    max_locator_len = max(len(section.locator) for section in deepest)
    owners = [section for section in deepest if len(section.locator) == max_locator_len]
    if len(owners) != 1:
        raise SectionError(
            "block ownership is ambiguous across sections",
            kind="ambiguous_section",
        )
    return owners[0]


def section_fingerprint(element: Element) -> str:
    """Hash one element's canonical XML form.

    Args:
        element: Section root or block element.

    Returns:
        ``sha256:`` prefixed hex digest.
    """
    return _fingerprint_elements([element])


def _fingerprint_elements(elements: list[Element]) -> str:
    """Compute a SHA-256 fingerprint over canonical XML for ``elements``.

    Args:
        elements: Blocks belonging to one section, in order.

    Returns:
        ``sha256:`` prefixed hex digest of UTF-8 canonical bytes.
    """
    chunks = [_canonical_xml(element) for element in elements]
    digest = hashlib.sha256("".join(chunks).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_xml(element: Element) -> str:
    """Serialize an element with unambiguous structure and escaped payloads.

    Encoding covers local tag, sorted non-volatile attributes, element text,
    each child subtree, and each child tail. Text and attribute values are
    escaped so literal ``&lt;b&gt;x&lt;/b&gt;`` cannot collide with a real
    ``<b>`` child. Child boundaries use explicit markers so text/tail splits
    remain distinct. Only documented volatile block/revision ids are omitted;
    changing id dialect or id values alone does not change the fingerprint.

    Args:
        element: Element to canonicalize.

    Returns:
        Canonical string suitable for hashing.
    """
    tag = _local(element.tag)
    attrs = {
        key: value
        for key, value in element.attrib.items()
        if key not in _VOLATILE_ATTRS and not key.startswith("_wenlint")
    }
    attr_text = "".join(
        f" @{_escape(key)}={_escape(attrs[key])}" for key in sorted(attrs)
    )
    parts = [f"<{tag}{attr_text}>", _escape(element.text or "")]
    for child in element:
        parts.append("(")
        parts.append(_canonical_xml(child))
        parts.append("^")
        parts.append(_escape(child.tail or ""))
        parts.append(")")
    parts.append(f"</{tag}>")
    return "".join(parts)


def _escape(value: str) -> str:
    """Escape delimiter and markup-significant characters in fingerprint payloads.

    Args:
        value: Raw attribute value, text, or tail.

    Returns:
        Escaped string that cannot introduce false tag or boundary markers.
    """
    return (
        value.replace("\\", "\\\\")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("^", "\\^")
        .replace("@", "\\@")
        .replace("=", "\\=")
    )


def _local(tag: str) -> str:
    """Return lowercase local tag name."""
    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    return tag.lower()
