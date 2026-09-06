"""Bounded ``lark-cli`` subprocess adapter for Feishu Docx/Wiki I/O.

All invocations use argv arrays with ``shell=False``. Document URLs, tokens,
and XML travel as single argv values so hostile characters cannot become shell
syntax. stdout/stderr are capped and never attached wholesale to exceptions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

from wenlint.feishu.models import DocumentRef

_STDOUT_LIMIT = 20 * 1024 * 1024
_STDERR_LIMIT = 1 * 1024 * 1024
_TERMINATE_GRACE_SECONDS = 1.0

_PROBE_FETCH_NEEDLES = (
    "docs",
    "+fetch",
    "--doc-format",
    "xml",
    "--detail",
    "full",
    "--as",
    "user",
)
_PROBE_UPDATE_NEEDLES = (
    "docs",
    "+update",
    "block_replace",
    "--revision-id",
    "--as",
    "user",
)


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
        self.fetch_timeout = fetch_timeout
        self.update_timeout = update_timeout

    def probe(self) -> str:
        """Verify required CLI capabilities and return version text.

        Returns:
            Version string from ``lark-cli --version``.

        Raises:
            LarkCliError: If the executable is missing or required flags or
                commands are absent from help output.
        """
        version = self._run(["--version"], timeout=10.0, expect_json=False)
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
        missing: list[str] = []
        for needle in _PROBE_FETCH_NEEDLES:
            if needle not in fetch_help:
                missing.append(f"fetch:{needle}")
        for needle in _PROBE_UPDATE_NEEDLES:
            if needle not in update_help:
                missing.append(f"update:{needle}")
        if "wiki" not in fetch_help.lower() and "/wiki/" not in fetch_help.lower():
            # Capability gate prefers explicit wiki mention; tolerate docs that
            # document URL forms without the literal word when +fetch exists.
            if "wiki" not in version.lower():
                missing.append("fetch:wiki")
        if missing:
            raise LarkCliError(
                "incompatible_cli",
                "lark-cli is missing required Feishu document capabilities",
                retryable=False,
                details={"missing_capabilities": missing, "version": version.strip()},
            )
        return version.strip()

    def fetch(self, ref: DocumentRef) -> Mapping[str, object]:
        """Fetch a Docx/Wiki document as XML ``full`` JSON using user identity.

        Args:
            ref: Document reference; may still be unresolved for Wiki inputs.

        Returns:
            Parsed JSON object with top-level ``ok is True``.

        Raises:
            LarkCliError: On process, protocol, auth, or schema failures.
        """
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
                "--format",
                "json",
            ],
            timeout=self.fetch_timeout,
            expect_json=True,
        )
        assert isinstance(payload, dict)
        self._require_ok(payload)
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
        if "revision_id" not in document:
            raise LarkCliError(
                "missing_revision",
                "fetch response is missing document revision_id",
                retryable=False,
            )
        return payload

    def replace_block(
        self,
        ref: DocumentRef,
        block_id: str,
        xml: str,
        revision_id: int,
    ) -> Mapping[str, object]:
        """Replace one block with complete XML under an explicit revision.

        Args:
            ref: Resolved document reference with canonical Docx identity.
            block_id: Latest block id from the current snapshot.
            xml: Complete patched block XML (never logged by this adapter).
            revision_id: Explicit positive revision; ``-1`` is rejected.

        Returns:
            Parsed JSON object whose update ``result`` is ``success``.

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
        if revision_id < 0:
            raise LarkCliError(
                "invalid_revision",
                "explicit revision_id is required; revision_id=-1 is forbidden",
                retryable=False,
            )
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
                "--format",
                "json",
            ],
            timeout=self.update_timeout,
            expect_json=True,
        )
        assert isinstance(payload, dict)
        self._require_ok(payload)
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
        return payload

    def _require_ok(self, payload: Mapping[str, object]) -> None:
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
            message = str(error.get("message") or message)
            if "hint" in error:
                details["hint"] = error["hint"]
            if "missing_scopes" in error:
                details["missing_scopes"] = error["missing_scopes"]
            retryable = kind in {"network", "timeout"}
        raise LarkCliError(kind, message, retryable=retryable, details=details)

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
            expect_json: When true, parse stdout as a JSON object.

        Returns:
            Parsed JSON object or decoded stdout text.

        Raises:
            LarkCliError: On missing executable, timeout, output limits,
                nonzero exits, or invalid JSON.
        """
        argv = [*self._argv_prefix, *args]
        executable = self._argv_prefix[0]
        if len(self._argv_prefix) == 1 and shutil.which(executable) is None:
            if not os.path.isfile(executable):
                raise LarkCliError(
                    "missing_executable",
                    "lark-cli executable was not found",
                    retryable=False,
                    details={"executable": executable},
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
                details={"executable": executable},
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


def _sanitized_env() -> dict[str, str]:
    """Build a minimal environment for child processes.

    Returns:
        Environment mapping that preserves PATH and fake-lark test knobs while
        avoiding wholesale dumping of secrets into logs.
    """
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TMP",
        "TEMP",
        "HOME",
        "USERPROFILE",
        "FAKE_LARK_MODE",
        "FAKE_LARK_RECORD",
        "FAKE_LARK_VERSION",
        "FAKE_LARK_SLEEP",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    # Ensure the Python interpreter can start the fake CLI under Windows.
    for key in ("PATHEXT", "COMSPEC", "PYTHONPATH", "VIRTUAL_ENV"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env
