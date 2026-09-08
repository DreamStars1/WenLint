"""Vue + pywebview desktop shell for WenLint."""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import __version__
from .agent import AgentConfig, AgentError, MAX_TEXT_CHARS, OpenAICompatibleAgent
from .profiles import PROFILES
from .scanner import scan_text


MAX_FILE_BYTES = 2 * 1024 * 1024
FILE_TYPES = (
    "文本文档 (*.txt;*.md;*.markdown;*.rst)",
    "所有文件 (*.*)",
)


def frontend_index() -> Path:
    """Locate Vite output both in a checkout and a PyInstaller bundle."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "wenlint" / "desktop_ui" / "index.html"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "desktop_ui" / "index.html"


class DesktopApi:
    """Narrow, JSON-compatible bridge exposed to the local Vue application."""

    def __init__(self) -> None:
        self._window: Any | None = None

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
            path = Path(selected[0])
            if path.stat().st_size > MAX_FILE_BYTES:
                return _failure("文件超过 2 MB，请拆分后再处理")
            content = path.read_text(encoding="utf-8-sig")
            if len(content) > MAX_TEXT_CHARS:
                return _failure(
                    f"文本超过 {MAX_TEXT_CHARS:,} 个字符，请拆分后再处理"
                )
            return {
                "ok": True,
                "cancelled": False,
                "path": str(path),
                "filename": path.name,
                "content": content,
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

    def agent_review(self, payload: object) -> dict[str, object]:
        """Call the configured endpoint; secrets are neither returned nor persisted."""

        if not isinstance(payload, dict):
            return _failure("请求格式无效")
        try:
            text, profile, filename = _document_request(payload)
            config = AgentConfig(
                base_url=_required_string(payload, "baseUrl", "Base URL"),
                api_key=_required_string(payload, "apiKey", "API Key"),
                model=_required_string(payload, "model", "模型名称"),
            )
            review = OpenAICompatibleAgent(config).review(
                text, profile=profile, filename=filename
            )
            return {
                "ok": True,
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
        if not isinstance(text, str) or not text:
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
        background_color="#0b1220",
        text_select=True,
    )
    api.attach_window(window)
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
