"""Parse and normalize Feishu Docx/Wiki document references.

URL parsing never contacts the network. Wiki tokens stay unresolved until a
validated fetch supplies the actual Docx ``document_id`` and canonical URL.
"""

from __future__ import annotations

import dataclasses
from urllib.parse import urlsplit

from wenlint.feishu.models import DocumentRef

_SUPPORTED_KINDS = {"docx", "wiki"}


class DocumentRefError(ValueError):
    """Raised when an input cannot be accepted as a Docx/Wiki URL."""

    def __init__(self, message: str, *, kind: str = "invalid_document_ref") -> None:
        """Store a stable error kind for CLI serialization.

        Args:
            message: Human-readable explanation without secrets.
            kind: Machine-stable error classifier.
        """
        super().__init__(message)
        self.kind = kind


def parse_document_ref(raw: str) -> DocumentRef:
    """Parse an HTTPS Docx or Wiki URL into an unresolved document reference.

    Query parameters are stripped from the stored URL because they may carry
    tracking data. A valid ``#share-...`` fragment is preserved for reading.
    ``document_id`` and ``canonical_url`` remain ``None`` until fetch.

    Args:
        raw: User-supplied URL string.

    Returns:
        Frozen unresolved ``DocumentRef``.

    Raises:
        DocumentRefError: If the scheme, host, path, credentials, or token are
            unsupported or ambiguous.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise DocumentRefError("document URL is required")

    parts = urlsplit(raw.strip())
    if parts.scheme.lower() != "https":
        raise DocumentRefError("only HTTPS Feishu/Lark document URLs are supported")
    if parts.username is not None or parts.password is not None:
        raise DocumentRefError("document URLs must not include credentials")
    if not parts.hostname:
        raise DocumentRefError("document URL is missing a host")

    path = parts.path or ""
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) != 2 or segments[0] not in _SUPPORTED_KINDS:
        raise DocumentRefError(
            "only /docx/<token> and /wiki/<token> HTTPS URLs are supported"
        )

    kind = segments[0]  # type: ignore[assignment]
    token = segments[1]
    if not token:
        raise DocumentRefError("document token must not be empty")

    fragment = ""
    if parts.fragment.startswith("share-"):
        fragment = f"#{parts.fragment}"

    # Drop query strings so logs and stored refs never retain tracking params.
    input_url = f"https://{parts.hostname.lower()}{path.rstrip('/')}{fragment}"
    if path.endswith("/") and not path.endswith("//"):
        # Keep exact token path without a trailing slash in the stored URL.
        input_url = f"https://{parts.hostname.lower()}/{kind}/{token}{fragment}"
    else:
        input_url = f"https://{parts.hostname.lower()}/{kind}/{token}{fragment}"

    return DocumentRef(
        input_url=input_url,
        kind=kind,  # type: ignore[arg-type]
        input_token=token,
        document_id=None,
        canonical_url=None,
    )


def resolve_fetched_docx_ref(
    input_ref: DocumentRef,
    document_id: str,
    url: str,
) -> DocumentRef:
    """Build a resolved Docx reference from validated fetch metadata.

    Args:
        input_ref: Original Docx/Wiki input reference.
        document_id: Actual Docx id returned by fetch.
        url: Canonical URL returned by fetch (query parameters ignored).

    Returns:
        Frozen ``DocumentRef`` with non-empty Docx ``document_id`` and
        ``canonical_url``.

    Raises:
        DocumentRefError: When the URL is not HTTPS ``/docx/<document_id>``.
    """
    if not document_id or not isinstance(document_id, str):
        raise DocumentRefError(
            "fetch response did not resolve a Docx document id",
            kind="unresolved_document",
        )
    if not url or not isinstance(url, str):
        raise DocumentRefError(
            "fetch response did not resolve a Docx canonical URL",
            kind="unresolved_document",
        )
    cleaned = url.split("?", 1)[0].split("#", 1)[0].strip()
    try:
        parsed = parse_document_ref(cleaned)
    except DocumentRefError as exc:
        raise DocumentRefError(
            "fetch canonical URL must be an HTTPS Docx URL",
            kind="unresolved_document",
        ) from exc
    if parsed.kind != "docx":
        raise DocumentRefError(
            "fetch must resolve Wiki/Docx inputs to a Docx canonical URL",
            kind="unresolved_document",
        )
    if parsed.input_token != document_id:
        raise DocumentRefError(
            "fetch document_id does not match the canonical Docx URL token",
            kind="unresolved_document",
        )
    canonical_url = (
        f"https://{urlsplit(parsed.input_url).hostname}/docx/{document_id}"
    )
    return dataclasses.replace(
        input_ref,
        document_id=document_id,
        canonical_url=canonical_url,
    )
