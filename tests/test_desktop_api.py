from __future__ import annotations

from wenlint.desktop import DesktopApi


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
