"""Parse and normalize Feishu Docx/Wiki document references.

URL parsing never contacts the network. Wiki tokens stay unresolved until a
validated fetch supplies the actual Docx ``document_id`` and canonical URL.
"""

from __future__ import annotations

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
