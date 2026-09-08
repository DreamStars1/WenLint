from __future__ import annotations

import codecs
import sys
from types import SimpleNamespace

import wenlint.desktop as desktop_module
from wenlint.agent import AgentReview
from wenlint.desktop import DesktopApi
from wenlint.workspace import WorkspaceSession


def test_static_scan_returns_json_compatible_findings() -> None:
    result = DesktopApi().static_scan(
        {
            "text": "系统仍然保留旧值，不再回填。",
            "profile": "general",
            "filename": "draft.md",
        }
    )

    assert result["ok"] is True
    assert result["count"] >= 2
    assert {item["match"] for item in result["findings"]} >= {"仍然", "不再"}


def test_static_scan_rejects_unknown_profile() -> None:
    result = DesktopApi().static_scan(
        {"text": "需要检查的文本", "profile": "unknown", "filename": "a.md"}
    )
    assert result == {"ok": False, "error": "检查场景无效"}


def test_app_info_is_the_single_source_for_frontend_limits() -> None:
    info = DesktopApi().app_info()
    assert info["maxFileBytes"] == 2 * 1024 * 1024
    assert info["maxTextChars"] == 200_000


def test_agent_validation_error_does_not_echo_key_or_document() -> None:
    secret = "secret-must-not-leak"
    source = "private-document-must-not-leak"
    result = DesktopApi().agent_review(
        {
            "text": source,
            "profile": "general",
            "filename": "a.md",
            "baseUrl": "not-a-url",
            "apiKey": secret,
            "model": "demo",
        }
    )
    rendered = str(result)
    assert result["ok"] is False
    assert secret not in rendered
    assert source not in rendered


def test_save_requires_an_attached_window() -> None:
    assert DesktopApi().save_revision({"text": "修改稿"}) == {
        "ok": False,
        "error": "窗口尚未就绪",
    }


def _open_standalone_file(api, target, monkeypatch) -> dict[str, object]:
    class FakeWindow:
        def create_file_dialog(self, *args, **kwargs):
            return [str(target)]

    fake_webview = SimpleNamespace(FileDialog=SimpleNamespace(OPEN=1))
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    api.attach_window(FakeWindow())
    return api.open_file()


def test_open_file_returns_hash_and_confirmed_save_updates_original(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "draft.md"
    target.write_text("原文", encoding="utf-8")
    api = DesktopApi()
    opened = _open_standalone_file(api, target, monkeypatch)

    result = api.save_original({"text": "修改稿", "confirmed": True})

    assert len(opened["sha256"]) == 64
    assert result["ok"] is True
    assert len(result["sha256"]) == 64
    assert target.read_text(encoding="utf-8") == "修改稿"


def test_save_original_requires_confirmation_and_rejects_external_change(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "draft.md"
    target.write_text("原文", encoding="utf-8")
    api = DesktopApi()
    _open_standalone_file(api, target, monkeypatch)

    unconfirmed = api.save_original({"text": "修改稿", "confirmed": False})
    target.write_text("外部修改", encoding="utf-8")
    conflicted = api.save_original({"text": "修改稿", "confirmed": True})

    assert unconfirmed["ok"] is False and "确认" in unconfirmed["error"]
    assert conflicted["ok"] is False and "其他程序修改" in conflicted["error"]
    assert target.read_text(encoding="utf-8") == "外部修改"


def test_save_original_preserves_utf8_bom(tmp_path, monkeypatch) -> None:
    target = tmp_path / "draft.md"
    target.write_bytes(codecs.BOM_UTF8 + "原文".encode())
    api = DesktopApi()
    _open_standalone_file(api, target, monkeypatch)

    result = api.save_original({"text": "修改稿", "confirmed": True})

    assert result["ok"] is True
    assert target.read_bytes() == codecs.BOM_UTF8 + "修改稿".encode()


def test_agent_review_reports_completed_state_even_without_changes(monkeypatch) -> None:
    class FakeAgent:
        def __init__(self, config) -> None:
            pass

        def review(self, text, *, profile, filename, workspace_context=""):
            return AgentReview(
                summary="语义复核完成，未发现需要修改的问题。",
                decisions=(),
                revised_text=text,
                model_calls=1,
                semantic_issue_count=0,
            )

    monkeypatch.setattr(desktop_module, "OpenAICompatibleAgent", FakeAgent)
    result = DesktopApi().agent_review(
        {
            "text": "表述清楚。",
            "profile": "general",
            "filename": "a.md",
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "secret",
            "model": "demo",
        }
    )

    assert result["ok"] is True
    assert result["reviewStatus"] == "completed"
    assert result["revisedText"] == "表述清楚。"
    assert result["decisions"] == []
    assert result["semanticIssueCount"] == 0
    assert result["modelCalls"] == 1
    assert isinstance(result["durationMs"], int)
    assert result["reviewedAt"].endswith("+00:00")


def test_workspace_read_and_confirmed_write_are_scoped_to_selected_root(tmp_path) -> None:
    target = tmp_path / "draft.md"
    target.write_text("原文", encoding="utf-8")
    api = DesktopApi()
    api._workspace = WorkspaceSession(tmp_path)

    indexed = api.workspace_index()
    opened = api.workspace_read({"path": "draft.md"})
    written = api.workspace_write(
        {
            "path": "draft.md",
            "text": "修改稿",
            "expectedSha256": opened["sha256"],
            "confirmed": True,
        }
    )

    assert indexed["files"][0]["path"] == "draft.md"
    assert opened["content"] == "原文"
    assert written["ok"] is True
    assert target.read_text(encoding="utf-8") == "修改稿"


def test_workspace_write_rejects_unconfirmed_change(tmp_path) -> None:
    target = tmp_path / "draft.md"
    target.write_text("原文", encoding="utf-8")
    api = DesktopApi()
    api._workspace = WorkspaceSession(tmp_path)
    opened = api.workspace_read({"path": "draft.md"})

    result = api.workspace_write(
        {
            "path": "draft.md",
            "text": "修改稿",
            "expectedSha256": opened["sha256"],
            "confirmed": False,
        }
    )

    assert result["ok"] is False
    assert "确认" in result["error"]
    assert target.read_text(encoding="utf-8") == "原文"


def test_workspace_api_can_write_empty_file(tmp_path) -> None:
    target = tmp_path / "draft.md"
    target.write_text("原文", encoding="utf-8")
    api = DesktopApi()
    api._workspace = WorkspaceSession(tmp_path)
    opened = api.workspace_read({"path": "draft.md"})

    result = api.workspace_write(
        {
            "path": "draft.md",
            "text": "",
            "expectedSha256": opened["sha256"],
            "confirmed": True,
        }
    )

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == ""
