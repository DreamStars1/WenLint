"""Conservative numeric change detection, not a factual or semantic verifier."""

import re


_NUMERIC_LITERAL = re.compile(r"[+\-−]?\d+(?:[.,:/-]\d+)*(?:[%％])?")


def numeric_literals_changed(before: str, after: str) -> bool:
    """Flag added, removed, reordered or changed Arabic numeric literals.

    Formatting conversions also require confirmation. Chinese numerals, units,
    names and logical qualifiers still require semantic review.
    """
    return _NUMERIC_LITERAL.findall(before) != _NUMERIC_LITERAL.findall(after)
