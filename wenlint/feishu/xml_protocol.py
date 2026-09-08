"""Feishu XML dialect helpers shared by projection, sections, and patches.

Callers resolve block identity through ``block_id_of`` instead of inspecting
``id`` / ``block-id`` / ``block_id`` attributes directly.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

_BLOCK_ID_ATTRS = ("id", "block-id", "block_id")


class XmlProtocolError(ValueError):
    """Raised when Feishu XML dialect attributes are ambiguous or invalid."""

    def __init__(self, message: str, *, kind: str = "xml_protocol_error") -> None:
        """Record a stable XML dialect failure kind.

        Args:
            message: Human-readable explanation without document bodies.
            kind: Machine-stable classifier.
        """
        super().__init__(message)
        self.kind = kind


def block_id_of(element: Element) -> str | None:
    """Return one unambiguous block id from ``id`` / ``block-id`` / ``block_id``.

    Args:
        element: XML element that may carry Feishu block identity attributes.

    Returns:
        The non-empty block id when exactly one distinct value is present, or
        ``None`` when none of the attributes are set.

    Raises:
        XmlProtocolError: When multiple attributes are present with conflicting
            non-empty values.
    """
    values: list[str] = []
    for attr in _BLOCK_ID_ATTRS:
        raw = element.attrib.get(attr)
        if isinstance(raw, str) and raw:
            values.append(raw)
    if not values:
        return None
    unique = set(values)
    if len(unique) > 1:
        raise XmlProtocolError(
            "conflicting Feishu block id attributes",
            kind="ambiguous_block_id",
        )
    return values[0]
