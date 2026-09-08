"""Bounded ``lark-cli`` subprocess adapter for Feishu Docx/Wiki I/O.

All invocations use argv arrays with ``shell=False``. Document URLs, tokens,
and XML travel as single argv values so hostile characters cannot become shell
syntax. stdout/stderr are capped and never attached wholesale to exceptions.

Callers receive normalized ``FetchedDocument`` / ``UpdateReceipt`` values and
never inspect raw CLI JSON schemas or dialect flags.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from wenlint.feishu.document import DocumentRefError, resolve_fetched_docx_ref
from wenlint.feishu.models import DocumentRef, FetchedDocument, UpdateReceipt

_STDOUT_LIMIT = 20 * 1024 * 1024
_STDERR_LIMIT = 1 * 1024 * 1024
_TERMINATE_GRACE_SECONDS = 1.0

_PROBE_FETCH_NEEDLES = (
    "--doc",
    "--doc-format",
    "xml",
    "--detail",
    "full",
    "--as",
    "user",
)
_PROBE_UPDATE_NEEDLES = (
    "block_replace",
    "--block-id",
    "--content",
    "--doc-format",
    "xml",
    "--revision-id",
    "--as",
    "user",
)

_MISSING_EXECUTABLE_HINT = (
    "Ensure the Node version containing lark-cli is active, "
    "or set WENLINT_LARK_CLI to its executable path."
)


class DocumentGateway(Protocol):
    """Minimal document I/O seam used by inspect and apply."""

    def fetch(self, ref: DocumentRef) -> FetchedDocument:
        """Fetch and normalize one document snapshot."""

    def replace_block(
        self,
        ref: DocumentRef,
        block_id: str,
        xml: str,
        revision_id: int,
    ) -> UpdateReceipt:
        """Replace one block under an explicit revision."""


@dataclass(frozen=True)
class _CliCapabilities:
    """Cached ``lark-cli`` dialect capabilities for argv construction."""

    version: str
    json_args: tuple[str, ...]


class LarkCliError(Exception):
    """Normalized ``lark-cli`` failure without document bodies or full logs.

    Attributes:
        kind: Stable machine-readable failure class.
        message: Compact human-readable explanation.
        retryable: Whether a later retry might succeed without user action.
        details: Safe structured extras such as ``missing_scopes`` or ``hint``.
    """

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        retryable: bool,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """Create a fail-closed adapter error.

        Args:
            kind: Stable error classifier used by CLI exit mapping.
            message: Short explanation safe to print on stderr.
            retryable: Whether the caller may retry without new credentials.
            details: Optional safe structured fields only.
        """
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retryable = retryable
        self.details = dict(details or {})


class LarkClient:
    """Run capability-gated ``lark-cli`` fetch and block_replace commands."""

    def __init__(
        self,
        executable: str | Sequence[str] = "lark-cli",
        fetch_timeout: float = 60.0,
        update_timeout: float = 30.0,
    ) -> None:
        """Configure executable path and hard timeouts.

        Args:
            executable: Program name/path or argv prefix (tests pass
                ``[python, fake_script]``).
            fetch_timeout: Maximum seconds for ``docs +fetch``.
            update_timeout: Maximum seconds for ``docs +update``.

        Raises:
            ValueError: If a timeout is not strictly positive.
        """
        if fetch_timeout <= 0 or update_timeout <= 0:
            raise ValueError("timeouts must be positive; they cannot be disabled")
        if isinstance(executable, str):
            self._argv_prefix: list[str] = [executable]
        else:
            self._argv_prefix = list(executable)
        # Allow tests and operators to override the executable without rewriting
        # argv construction for every call site.
        override = os.environ.get("WENLINT_LARK_CLI")
        if override and self._argv_prefix == ["lark-cli"]:
            if override.endswith(".py"):
                self._argv_prefix = [sys.executable, override]
            else:
                self._argv_prefix = [override]
        self.fetch_timeout = fetch_timeout
        self.update_timeout = update_timeout
        self._capabilities: _CliCapabilities | None = None

    def probe(self) -> str:
        """Verify required CLI capabilities and cache dialect settings.

        Returns:
            Version string from ``lark-cli --version``.

        Raises:
            LarkCliError: If the executable is missing or required flags or
                commands are absent from help output.
        """
        return self._ensure_capabilities().version

    def fetch(self, ref: DocumentRef) -> FetchedDocument:
        """Fetch a Docx/Wiki document as normalized XML with revision metadata.

        Args:
            ref: Document reference; may still be unresolved for Wiki inputs.

        Returns:
            Normalized ``FetchedDocument`` with resolved Docx identity.

        Raises:
            LarkCliError: On process, protocol, auth, or schema failures.
        """
        caps = self._ensure_capabilities()
        payload = self._run(
            [
                "docs",
                "+fetch",
                "--doc",
                ref.input_url,
                "--doc-format",
                "xml",
                "--detail",
                "full",
                "--as",
                "user",
                *caps.json_args,
            ],
            timeout=self.fetch_timeout,
            expect_json=True,
        )
        assert isinstance(payload, dict)
        return _normalize_fetch_payload(payload, ref)

    def replace_block(
        self,
        ref: DocumentRef,
        block_id: str,
        xml: str,
        revision_id: int,
    ) -> UpdateReceipt:
        """Replace one block with complete XML under an explicit revision.

        Args:
            ref: Resolved document reference with canonical Docx identity.
            block_id: Latest block id from the current snapshot.
            xml: Complete patched block XML (never logged by this adapter).
            revision_id: Explicit positive revision; ``revision_id <= 0`` is
                rejected before spawning.

        Returns:
            Normalized ``UpdateReceipt`` whose ``reported_revision_id`` is
            diagnostic only.

        Raises:
            LarkCliError: On unresolved refs, forbidden modes, or update
                failures including ``partial_success``.
        """
        if ref.document_id is None or ref.canonical_url is None:
            raise LarkCliError(
                "unresolved_document",
                "block replace requires a resolved Docx document reference",
                retryable=False,
            )
        if revision_id <= 0:
            raise LarkCliError(
                "invalid_revision",
                "explicit positive revision_id is required; revision_id<=0 is forbidden",
                retryable=False,
            )
        caps = self._ensure_capabilities()
        doc = ref.canonical_url
        payload = self._run(
            [
                "docs",
                "+update",
                "--doc",
                doc,
                "--command",
                "block_replace",
                "--block-id",
                block_id,
                "--content",
                xml,
                "--doc-format",
                "xml",
                "--revision-id",
                str(revision_id),
                "--as",
                "user",
                *caps.json_args,
            ],
            timeout=self.update_timeout,
            expect_json=True,
        )
        assert isinstance(payload, dict)
        return _normalize_update_payload(payload)

    def _ensure_capabilities(self) -> _CliCapabilities:
        """Probe once and cache dialect capabilities for later argv builds.

        Returns:
            Cached capability snapshot.

        Raises:
            LarkCliError: When required help needles are missing or JSON
                dialects disagree across fetch/update.
        """
        if self._capabilities is not None:
            return self._capabilities
        version = self._run(["--version"], timeout=10.0, expect_json=False)
        assert isinstance(version, str)
        fetch_help = self._run(
            ["docs", "+fetch", "--help"],
            timeout=10.0,
            expect_json=False,
        )
        update_help = self._run(
            ["docs", "+update", "--help"],
            timeout=10.0,
            expect_json=False,
        )
        assert isinstance(fetch_help, str)
        assert isinstance(update_help, str)
        missing: list[str] = []
        for needle in _PROBE_FETCH_NEEDLES:
            if needle not in fetch_help:
                missing.append(f"fetch:{needle}")
        for needle in _PROBE_UPDATE_NEEDLES:
            if needle not in update_help:
                missing.append(f"update:{needle}")
        if missing:
            raise LarkCliError(
                "incompatible_cli",
                "lark-cli is missing required Feishu document capabilities",
                retryable=False,
                details={"missing_capabilities": missing, "version": version.strip()},
            )
        fetch_json = "--format" in fetch_help and "json" in fetch_help
        update_json = "--format" in update_help and "json" in update_help
        if fetch_json != update_json:
            raise LarkCliError(
                "incompatible_cli",
                "lark-cli fetch/update JSON dialects disagree",
                retryable=False,
                details={
                    "missing_capabilities": [
                        f"fetch:format_json={fetch_json}",
                        f"update:format_json={update_json}",
                    ],
                    "version": version.strip(),
                },
            )
        json_args: tuple[str, ...] = ("--format", "json") if fetch_json else ()
        self._capabilities = _CliCapabilities(
            version=version.strip(),
            json_args=json_args,
        )
        return self._capabilities

    def _run(
        self,
        args: Sequence[str],
        *,
        timeout: float,
        expect_json: bool,
    ) -> dict[str, object] | str:
        """Execute ``lark-cli`` with capped pipes and normalized errors.

        Args:
            args: Arguments after the executable prefix.
            timeout: Hard wall-clock timeout in seconds.
            expect_json: When true, parse stdout as a JSON object; on nonzero
                exit, also attempt bounded JSON recovery from stdout then
                stderr before falling back to ``nonzero_exit``.

        Returns:
            Parsed JSON object or decoded stdout text.

        Raises:
            LarkCliError: On missing executable, timeout, output limits,
                nonzero exits, normalized CLI error envelopes, or invalid JSON.
        """
        argv = [*self._argv_prefix, *args]
        executable = self._argv_prefix[0]
        if len(self._argv_prefix) == 1 and shutil.which(executable) is None:
            if not os.path.isfile(executable):
                raise LarkCliError(
                    "missing_executable",
                    "lark-cli executable was not found",
                    retryable=False,
                    details={
                        "executable": executable,
                        "hint": _MISSING_EXECUTABLE_HINT,
                    },
                )

        try:
            proc = subprocess.Popen(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_sanitized_env(),
            )
        except FileNotFoundError as exc:
            raise LarkCliError(
                "missing_executable",
                "lark-cli executable was not found",
                retryable=False,
                details={
                    "executable": executable,
                    "hint": _MISSING_EXECUTABLE_HINT,
                },
            ) from exc

        stdout_buf = bytearray()
        stderr_buf = bytearray()
        overflow = threading.Event()

        def _reader(stream: Any, buf: bytearray, limit: int) -> None:
            assert stream is not None
            try:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    if len(buf) + len(chunk) > limit:
                        overflow.set()
                        break
                    buf.extend(chunk)
            finally:
                stream.close()

        stdout_thread = threading.Thread(
            target=_reader,
            args=(proc.stdout, stdout_buf, _STDOUT_LIMIT),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_reader,
            args=(proc.stderr, stderr_buf, _STDERR_LIMIT),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        deadline = time.monotonic() + timeout
        timed_out = False
        while True:
            if overflow.is_set():
                _terminate(proc)
                stdout_thread.join(timeout=1)
                stderr_thread.join(timeout=1)
                raise LarkCliError(
                    "output_limit",
                    "lark-cli output exceeded the configured size limit",
                    retryable=False,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _terminate(proc)
                break
            try:
                proc.wait(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue

        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)

        if timed_out:
            raise LarkCliError(
                "timeout",
                "lark-cli timed out",
                retryable=True,
            )

        if overflow.is_set():
            raise LarkCliError(
                "output_limit",
                "lark-cli output exceeded the configured size limit",
                retryable=False,
            )

        try:
            stdout_text = bytes(stdout_buf).decode("utf-8")
            stderr_text = bytes(stderr_buf).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LarkCliError(
                "invalid_encoding",
                "lark-cli output was not valid UTF-8",
                retryable=False,
            ) from exc

        if proc.returncode != 0:
            if expect_json:
                for text in (stdout_text, stderr_text):
                    parsed_error = _parse_bounded_json_object(text)
                    if parsed_error is not None and _is_ok_false_error_object(
                        parsed_error
                    ):
                        _require_ok(parsed_error)
            raise LarkCliError(
                "nonzero_exit",
                "lark-cli exited with a nonzero status",
                retryable=False,
                details={"exit_code": proc.returncode},
            )

        if not expect_json:
            return stdout_text or stderr_text

        try:
            parsed = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            raise LarkCliError(
                "invalid_json",
                "lark-cli stdout was not valid JSON",
                retryable=False,
            ) from exc
        if not isinstance(parsed, dict):
            raise LarkCliError(
                "invalid_json",
                "lark-cli JSON root must be an object",
                retryable=False,
            )
        return parsed


def _normalize_fetch_payload(
    payload: Mapping[str, object],
    ref: DocumentRef,
) -> FetchedDocument:
    """Normalize legacy/modern fetch JSON into ``FetchedDocument``.

    Args:
        payload: Parsed CLI JSON object.
        ref: Input document reference used for trusted host reconstruction.

    Returns:
        Normalized fetched document.

    Raises:
        LarkCliError: On schema, ambiguity, or resolution failures.
    """
    _require_ok(payload)
    data = payload.get("data")
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

    nested = document.get("content")
    legacy = data.get("content")
    nested_ok = isinstance(nested, str) and bool(nested)
    legacy_ok = isinstance(legacy, str) and bool(legacy)
    if nested_ok and legacy_ok and nested != legacy:
        raise LarkCliError(
            "ambiguous_content",
            "fetch response contains conflicting XML content paths",
            retryable=False,
        )
    if nested_ok:
        content = nested
    elif legacy_ok:
        content = legacy
    else:
        raise LarkCliError(
            "invalid_response",
            "fetch response is missing XML content",
            retryable=False,
        )
    assert isinstance(content, str)

    document_id = document.get("document_id")
    if not isinstance(document_id, str) or not document_id:
        raise LarkCliError(
            "unresolved_document",
            "fetch response did not resolve a Docx document id",
            retryable=False,
        )

    raw_revision = document.get("revision_id")
    if "revision_id" not in document:
        raise LarkCliError(
            "missing_revision",
            "fetch response is missing document revision_id",
            retryable=False,
        )
    if isinstance(raw_revision, bool) or not isinstance(raw_revision, int) or raw_revision <= 0:
        raise LarkCliError(
            "invalid_response",
            "fetch response revision_id must be a positive integer",
            retryable=False,
        )

    raw_url = document.get("url")
    if isinstance(raw_url, str) and raw_url:
        candidate_url = raw_url
    else:
        host = urlsplit(ref.input_url).hostname
        if not host:
            raise LarkCliError(
                "unresolved_document",
                "fetch response did not resolve a Docx canonical URL",
                retryable=False,
            )
        candidate_url = f"https://{host}/docx/{document_id}"

    try:
        resolved = resolve_fetched_docx_ref(ref, document_id, candidate_url)
    except DocumentRefError as exc:
        raise LarkCliError(
            getattr(exc, "kind", "unresolved_document"),
            str(exc),
            retryable=False,
        ) from exc

    return FetchedDocument(ref=resolved, revision_id=raw_revision, xml=content)


def _normalize_update_payload(payload: Mapping[str, object]) -> UpdateReceipt:
    """Normalize update JSON into ``UpdateReceipt``.

    Args:
        payload: Parsed CLI JSON object.

    Returns:
        Normalized success receipt.

    Raises:
        LarkCliError: When ``ok`` is false or ``result`` is not ``success``.
    """
    _require_ok(payload)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise LarkCliError(
            "invalid_response",
            "update response is missing data object",
            retryable=False,
        )
    result = data.get("result")
    if result != "success":
        kind = "partial_success" if result == "partial_success" else "update_failed"
        raise LarkCliError(
            kind,
            f"block replace did not succeed (result={result!r})",
            retryable=False,
            details={"result": result},
        )

    warnings: list[object] = []
    top_warnings = payload.get("warnings")
    if isinstance(top_warnings, list):
        warnings.extend(top_warnings)
    raw_warnings = data.get("warnings")
    if isinstance(raw_warnings, list):
        warnings.extend(raw_warnings)

    reported = data.get("revision_id")
    reported_revision: int | None
    if isinstance(reported, bool) or not isinstance(reported, int):
        reported_revision = None
    else:
        reported_revision = reported

    return UpdateReceipt(
        result="success",
        reported_revision_id=reported_revision,
        warnings=tuple(warnings),
    )


def _require_ok(payload: Mapping[str, object]) -> None:
    """Fail closed unless top-level ``ok`` is exactly ``True``.

    Args:
        payload: Parsed JSON object from ``lark-cli``.

    Raises:
        LarkCliError: When ``ok`` is missing or false.
    """
    if payload.get("ok") is True:
        return
    error = payload.get("error")
    kind = "protocol_error"
    message = "lark-cli returned ok=false"
    retryable = False
    details: dict[str, object] = {}
    if isinstance(error, Mapping):
        err_type = str(error.get("type") or error.get("code") or "protocol_error")
        kind = err_type
        message = _safe_error_message(kind, error.get("message"))
        if "hint" in error:
            details["hint"] = error["hint"]
        if "missing_scopes" in error:
            details["missing_scopes"] = error["missing_scopes"]
        retryable = kind in {"network", "timeout"}
    raise LarkCliError(kind, message, retryable=retryable, details=details)


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Terminate a subprocess, escalating to kill after a short grace period.

    Args:
        proc: Running child process to stop.
    """
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=_TERMINATE_GRACE_SECONDS)


def _parse_bounded_json_object(text: str) -> dict[str, object] | None:
    """Parse a JSON object from already-bounded pipe text.

    Args:
        text: UTF-8 decoded stdout or stderr content within size limits.

    Returns:
        A JSON object mapping, or ``None`` when the text is not a JSON object.
    """
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _is_ok_false_error_object(payload: Mapping[str, object]) -> bool:
    """Return whether payload is an ``ok=false`` / ``error`` envelope.

    Args:
        payload: Candidate JSON object from a nonzero CLI exit.

    Returns:
        True when the object should be normalized via ``_require_ok``.
    """
    if payload.get("ok") is False:
        return True
    error = payload.get("error")
    return isinstance(error, Mapping) and payload.get("ok") is not True


def _safe_error_message(kind: str, raw: object) -> str:
    """Return a compact error message that never echoes document bodies.

    Args:
        kind: Stable error classifier.
        raw: Untrusted remote ``error.message`` value.

    Returns:
        A short safe message suitable for stderr JSON.
    """
    fallback = f"lark-cli reported {kind}"
    if not isinstance(raw, str) or not raw.strip():
        return fallback
    text = raw.strip()
    if len(text) > 160:
        return fallback
    lowered = text.lower()
    if "<" in text or ">" in text or "http://" in lowered or "https://" in lowered:
        return fallback
    if any(marker in text for marker in ("block-id", "<p", "<h1", "<?xml", "{")):
        return fallback
    return text


def _sanitized_env() -> dict[str, str]:
    """Build a minimal environment for child processes.

    Returns:
        Environment mapping that preserves PATH, Windows AppData path values,
        and fake-lark test knobs while avoiding wholesale dumping of secrets.
    """
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TMP",
        "TEMP",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "FAKE_LARK_MODE",
        "FAKE_LARK_RECORD",
        "FAKE_LARK_VERSION",
        "FAKE_LARK_SLEEP",
        "FAKE_LARK_STATE",
        "FAKE_LARK_LEAK",
        "FAKE_LARK_DIALECT",
        "WENLINT_LARK_CLI",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    # Ensure the Python interpreter can start the fake CLI under Windows.
    for key in ("PATHEXT", "COMSPEC", "PYTHONPATH", "VIRTUAL_ENV"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env
