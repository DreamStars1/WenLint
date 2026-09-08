"""Vue + pywebview desktop shell for WenLint."""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from . import __version__
from .agent import AgentConfig, AgentError, MAX_TEXT_CHARS, OpenAICompatibleAgent
from .profiles import PROFILES
from .scanner import scan_text
from .workspace import WorkspaceError, WorkspaceSession, write_checked_file
from .workspace_agent import WorkspaceAgentAccess
from .review_jobs import ReviewJobs


MAX_FILE_BYTES = 2 * 1024 * 1024
FILE_TYPES = (
    "文本文档 (*.txt;*.md;*.markdown;*.rst)",
    "所有文件 (*.*)",
)


@dataclass
class OpenedFile:
    path: Path
    sha256: str


def frontend_index() -> Path:
    """Locate Vite output both in a checkout and a PyInstaller bundle."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "wenlint" / "desktop_ui" / "index.html"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "desktop_ui" / "index.html"


class DesktopApi:
    """Narrow, JSON-compatible bridge exposed to the local Vue application."""

    def __init__(self) -> None:
        self._window: Any | None = None
        self._workspace: WorkspaceSession | None = None
        self._opened_file: OpenedFile | None = None
        self._review_jobs = ReviewJobs()

    def attach_window(self, window: Any) -> None:
        self._window = window

    def app_info(self) -> dict[str, object]:
        return {
            "ok": True,
            "version": __version__,
            "profiles": sorted(PROFILES),
            "maxTextChars": MAX_TEXT_CHARS,
            "maxFileBytes": MAX_FILE_BYTES,
        }

    def open_workspace(self) -> dict[str, object]:
        if self._window is None:
            return _failure("窗口尚未就绪")
        try:
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.FOLDER,
                allow_multiple=False,
            )
            if not selected:
                return {"ok": True, "cancelled": True}
            self._workspace = WorkspaceSession(selected[0])
            self._opened_file = None
            return {
                "ok": True,
                "cancelled": False,
                "root": str(self._workspace.root),
                "name": self._workspace.name,
                "files": self._workspace.index(),
            }
        except (OSError, WorkspaceError) as exc:
            message = str(exc) if isinstance(exc, WorkspaceError) else "无法打开工作区"
            return _failure(message)

    def workspace_index(self) -> dict[str, object]:
        if self._workspace is None:
            return _failure("尚未选择工作区")
        return {
            "ok": True,
            "root": str(self._workspace.root),
            "name": self._workspace.name,
            "files": self._workspace.index(),
        }

    def workspace_read(self, payload: object) -> dict[str, object]:
        if self._workspace is None:
            return _failure("尚未选择工作区")
        if not isinstance(payload, dict):
            return _failure("请求格式无效")
        try:
            path = _required_string(payload, "path", "工作区文件路径")
            result = self._workspace.read(path)
            self._opened_file = None
            return {"ok": True, **result}
        except (ValueError, WorkspaceError) as exc:
            return _failure(str(exc))

    def workspace_write(self, payload: object) -> dict[str, object]:
        if self._workspace is None:
            return _failure("尚未选择工作区")
        if not isinstance(payload, dict):
            return _failure("请求格式无效")
        try:
            path = _required_string(payload, "path", "工作区文件路径")
            text = payload.get("text")
            if not isinstance(text, str):
                raise ValueError("待写回内容必须是文本")
            expected_hash = _required_string(
                payload, "expectedSha256", "文件内容校验值"
            )
            confirmed = payload.get("confirmed") is True
            return {
                "ok": True,
                **self._workspace.write(
                    path,
                    text,
                    expected_hash,
                    confirmed=confirmed,
                ),
            }
        except (ValueError, WorkspaceError) as exc:
            return _failure(str(exc))

    def open_file(self) -> dict[str, object]:
        if self._window is None:
            return _failure("窗口尚未就绪")
        try:
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=False,
                file_types=FILE_TYPES,
            )
            if not selected:
                return {"ok": True, "cancelled": True}
            path = Path(selected[0]).resolve(strict=True)
            raw = path.read_bytes()
            if len(raw) > MAX_FILE_BYTES:
                return _failure("文件超过 2 MB，请拆分后再处理")
            content = raw.decode("utf-8-sig")
            if len(content) > MAX_TEXT_CHARS:
                return _failure(
                    f"文本超过 {MAX_TEXT_CHARS:,} 个字符，请拆分后再处理"
                )
            digest = hashlib.sha256(raw).hexdigest()
            self._opened_file = OpenedFile(path=path, sha256=digest)
            return {
                "ok": True,
                "cancelled": False,
                "path": str(path),
                "filename": path.name,
                "content": content,
                "sha256": digest,
            }
        except (OSError, UnicodeError) as exc:
            return _failure(f"无法读取文件：{type(exc).__name__}")

    def static_scan(self, payload: object) -> dict[str, object]:
        try:
            text, profile, filename = _document_request(payload)
            findings = scan_text(text, profile=profile, filename=filename)
            return {"ok": True, "findings": findings, "count": len(findings)}
        except ValueError as exc:
            return _failure(str(exc))
        except Exception as exc:
            return _failure(f"静态检查失败（{type(exc).__name__}）")

    def start_agent_review(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            return _failure('请求格式无效')
        snapshot = dict(payload)
        return self._review_jobs.start(
            lambda emit, cancel: self.agent_review(snapshot, on_event=emit, cancel_event=cancel)
        )

    def agent_review_status(self, payload: object) -> dict[str, object]:
        return self._review_jobs.status(payload)

    def cancel_agent_review(self, payload: object) -> dict[str, object]:
        return self._review_jobs.cancel(payload)

    def agent_review(self, payload: object, *, on_event=None, cancel_event=None) -> dict[str, object]:
        """Call the configured endpoint; secrets are neither returned nor persisted."""

        if not isinstance(payload, dict):
            return _failure("请求格式无效")
        try:
            started = perf_counter()
            text, profile, filename = _document_request(payload)
            if payload.get('demo') is True:
                from .offline_demo import review_demo
                return review_demo(text, profile, filename, on_event, cancel_event)
            config = AgentConfig(
                base_url=_required_string(payload, "baseUrl", "Base URL"),
                api_key=_required_string(payload, "apiKey", "API Key"),
                model=_required_string(payload, "model", "模型名称"),
            )
            workspace_context = ""
            workspace_access = None
            workspace_path = payload.get("workspacePath")
            if workspace_path:
                if self._workspace is None:
                    raise ValueError("当前文件关联的工作区已经断开")
                if not isinstance(workspace_path, str):
                    raise ValueError("工作区文件路径无效")
                if payload.get('use_workspace_tools') is True:
                    workspace_access = WorkspaceAgentAccess(self._workspace, workspace_path)
                else:
                    workspace_context = self._workspace.review_context(workspace_path)
            options = {}
            if on_event is not None:
                options.update(on_event=on_event, cancel_event=cancel_event)
            if workspace_access is not None:
                options['workspace_access'] = workspace_access
            review = OpenAICompatibleAgent(config).review(
                text,
                profile=profile,
                filename=filename,
                workspace_context=workspace_context,
                **options,
            )
            return {
                "ok": True,
                "reviewStatus": "completed",
                "reviewedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "durationMs": round((perf_counter() - started) * 1000),
                "modelCalls": review.model_calls,
                "semanticIssueCount": review.semantic_issue_count,
                "summary": review.summary,
                "decisions": [asdict(item) for item in review.decisions],
                "revisedText": review.revised_text,
            }
        except (AgentError, ValueError) as exc:
            return _failure(str(exc))
        except Exception as exc:
            return _failure(f"Agent 审查失败（{type(exc).__name__}）")

    def save_revision(self, payload: object) -> dict[str, object]:
        if self._window is None:
            return _failure("窗口尚未就绪")
        if not isinstance(payload, dict):
            return _failure("请求格式无效")
        text = payload.get("text")
        if not isinstance(text, str):
            return _failure("没有可保存的修改稿")
        suggested = payload.get("suggestedName", "wenlint-review.revised.md")
        if not isinstance(suggested, str) or not suggested.strip():
            suggested = "wenlint-review.revised.md"
        suggested = Path(suggested).name
        try:
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=suggested,
                file_types=FILE_TYPES,
            )
            if not selected:
                return {"ok": True, "cancelled": True}
            target = Path(selected[0])
            target.write_text(text, encoding="utf-8")
            return {"ok": True, "cancelled": False, "path": str(target)}
        except OSError as exc:
            return _failure(f"保存失败：{type(exc).__name__}")

    def save_original(self, payload: object) -> dict[str, object]:
        """Save to the last file selected by the native open dialog."""

        if self._opened_file is None:
            return _failure("当前文档没有可保存的原文件")
        if not isinstance(payload, dict):
            return _failure("请求格式无效")
        text = payload.get("text")
        if not isinstance(text, str):
            return _failure("待保存内容必须是文本")
        try:
            digest = write_checked_file(
                self._opened_file.path,
                text,
                self._opened_file.sha256,
                confirmed=payload.get("confirmed") is True,
                confirmation_error="保存到原文件前必须由用户明确确认",
            )
            self._opened_file.sha256 = digest
            return {
                "ok": True,
                "path": str(self._opened_file.path),
                "sha256": digest,
            }
        except WorkspaceError as exc:
            return _failure(str(exc))


def _document_request(payload: object) -> tuple[str, str, str]:
    if not isinstance(payload, dict):
        raise ValueError("请求格式无效")
    text = _required_string(payload, "text", "待审查文本")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"文本过长，当前最多支持 {MAX_TEXT_CHARS:,} 个字符")
    profile = payload.get("profile", "general")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError("检查场景无效")
    filename = payload.get("filename", "<desktop>")
    if not isinstance(filename, str) or not filename:
        filename = "<desktop>"
    return text, profile, Path(filename).name


def _required_string(payload: dict[str, object], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    return value


def _failure(message: str) -> dict[str, object]:
    return {"ok": False, "error": message}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wenlint-desktop", add_help=False)
    parser.add_argument("--self-test", action="store_true")
    args, _ = parser.parse_known_args(argv)
    index = frontend_index()
    if not index.is_file():
        print(f"WenLint desktop assets are missing: {index}", file=sys.stderr)
        return 2
    try:
        import webview
        getattr(webview.FileDialog, "OPEN")
        getattr(webview.FileDialog, "SAVE")
        getattr(webview.FileDialog, "FOLDER")
    except (ImportError, AttributeError) as exc:
        print(
            "WenLint desktop runtime is unavailable; install with the desktop extra",
            file=sys.stderr,
        )
        return 3
    if args.self_test:
        return 0

    api = DesktopApi()
    window = webview.create_window(
        f"文尺 WenLint {__version__}",
        index.as_uri(),
        js_api=api,
        width=1280,
        height=820,
        min_size=(960, 680),
        background_color="#f3f1ed",
        text_select=True,
    )
    api.attach_window(window)
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
