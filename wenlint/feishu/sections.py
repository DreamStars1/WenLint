"""Section boundaries, structural locators, and canonical fingerprints.

Fingerprints ignore volatile block ids and revisions so collaborators renaming
ids do not invalidate an unchanged chapter, while any text or semantic
structure change does.
"""

from __future__ import annotations

import hashlib
from xml.etree.ElementTree import Element

from wenlint.feishu.models import DocumentSnapshot, Section

_HEADING_TAGS = {f"h{i}" for i in range(1, 10)}
_VOLATILE_ATTRS = {
    "block-id",
    "block_id",
    "revision-id",
    "revision_id",
    "id",
    "record-id",
    "record_id",
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
            block_id = block.attrib.get("block-id") or block.attrib.get("block_id") or ""
            title = "".join(block.itertext())
            headings.append((index, level, title, block_id))

    if not headings:
        block_ids = tuple(
            (block.attrib.get("block-id") or block.attrib.get("block_id") or "")
            for block in blocks
        )
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
                block_ids=tuple(
                    (b.attrib.get("block-id") or b.attrib.get("block_id") or "")
                    for b in lead_blocks
                ),
                fingerprint=_fingerprint_elements(lead_blocks),
            )
        )

    sibling_counters: dict[tuple[str, ...], dict[str, int]] = {}
    path_titles: list[str] = []
    path_levels: list[int] = []

    for heading_pos, (start, level, title, _block_id) in enumerate(headings):
        while path_levels and path_levels[-1] >= level:
            path_levels.pop()
            path_titles.pop()

        path_titles.append(title)
        path_levels.append(level)
        path_key = tuple(path_titles[:-1])
        counters = sibling_counters.setdefault(path_key, {})
        counters[title] = counters.get(title, 0) + 1
        ordinal = counters[title]
        locator = "/".join(
            f"{part}[{_ordinal_for(path_titles[: index + 1], sibling_counters)}]"
            for index, part in enumerate(path_titles)
        )
        # Recompute locator with stable ordinals along the full path.
        locator = _locator_for(path_titles, path_levels, headings, heading_pos)

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
                block_ids=tuple(
                    (b.attrib.get("block-id") or b.attrib.get("block_id") or "")
                    for b in section_blocks
                ),
                fingerprint=_fingerprint_elements(section_blocks),
            )
        )

    return tuple(sections)


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


def section_fingerprint(element: Element) -> str:
    """Hash one element's canonical XML form.

    Args:
        element: Section root or block element.

    Returns:
        ``sha256:`` prefixed hex digest.
    """
    return _fingerprint_elements([element])


def _locator_for(
    path_titles: list[str],
    path_levels: list[int],
    headings: list[tuple[int, int, str, str]],
    heading_pos: int,
) -> str:
    """Build a locator with one-based same-name sibling ordinals.

    Args:
        path_titles: Title stack for the current heading.
        path_levels: Level stack aligned with ``path_titles``.
        headings: All headings in document order.
        heading_pos: Index of the current heading in ``headings``.

    Returns:
        Locator such as ``同名[2]/子节[1]``.
    """
    parts: list[str] = []
    for depth, title in enumerate(path_titles):
        level = path_levels[depth]
        parent_titles = tuple(path_titles[:depth])
        ordinal = 0
        stack_titles: list[str] = []
        stack_levels: list[int] = []
        for index, (_start, heading_level, heading_title, _) in enumerate(headings):
            while stack_levels and stack_levels[-1] >= heading_level:
                stack_levels.pop()
                stack_titles.pop()
            stack_titles.append(heading_title)
            stack_levels.append(heading_level)
            if index > heading_pos:
                break
            if (
                heading_level == level
                and heading_title == title
                and tuple(stack_titles[:-1]) == parent_titles
            ):
                ordinal += 1
            if index == heading_pos:
                break
        parts.append(f"{title}[{ordinal}]")
    return "/".join(parts)


def _ordinal_for(
    titles: list[str], sibling_counters: dict[tuple[str, ...], dict[str, int]]
) -> int:
    """Compatibility helper retained for clarity in locator construction."""
    parent = tuple(titles[:-1])
    return sibling_counters.get(parent, {}).get(titles[-1], 1)


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
    """Serialize an element with volatile ids removed and attributes sorted.

    Args:
        element: Element to canonicalize.

    Returns:
        Canonical XML string.
    """
    tag = _local(element.tag)
    attrs = {
        key: value
        for key, value in element.attrib.items()
        if key not in _VOLATILE_ATTRS and not key.startswith("_wenlint")
    }
    attr_text = "".join(f' {key}="{attrs[key]}"' for key in sorted(attrs))
    children = list(element)
    if not children and not element.text and not element.tail:
        return f"<{tag}{attr_text}></{tag}>"

    parts = [f"<{tag}{attr_text}>"]
    if element.text:
        parts.append(element.text)
    for child in children:
        parts.append(_canonical_xml(child))
        if child.tail:
            parts.append(child.tail)
    parts.append(f"</{tag}>")
    return "".join(parts)


def _local(tag: str) -> str:
    """Return lowercase local tag name."""
    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    return tag.lower()
