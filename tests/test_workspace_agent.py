from __future__ import annotations

import json

from wenlint.workspace import WorkspaceSession
from wenlint.workspace_agent import WorkspaceAgentAccess


def _execute(access: WorkspaceAgentAccess, name: str, arguments: dict) -> dict:
    return json.loads(access.execute(name, json.dumps(arguments)))


def test_agent_context_does_not_expose_workspace_index_or_sibling_content(tmp_path) -> None:
    (tmp_path / "draft.md").write_text("当前正文", encoding="utf-8")
    (tmp_path / "private-notes.md").write_text("内部证据", encoding="utf-8")

    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")

    rendered = json.dumps(access.context, ensure_ascii=False)
    assert "draft.md" in rendered
    assert "private-notes.md" not in rendered
    assert "内部证据" not in rendered


def test_agent_lists_searches_and_reads_only_requested_material(tmp_path) -> None:
    (tmp_path / "draft.md").write_text("当前正文", encoding="utf-8")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "baseline.md").write_text(
        "第一行\n登录超时为 20 秒。\n第三行\n第四行", encoding="utf-8"
    )
    (tmp_path / "other.md").write_text("不应被读取", encoding="utf-8")
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")

    listed = _execute(
        access,
        "list_workspace_files",
        {"query": "baseline", "limit": 10},
    )
    searched = _execute(
        access,
        "search_workspace_text",
        {"query": "登录超时", "path_prefix": "evidence", "limit": 10},
    )
    read = _execute(
        access,
        "read_workspace_file",
        {"path": "evidence/baseline.md", "start_line": 2, "line_count": 2},
    )

    assert [item["path"] for item in listed["files"]] == ["evidence/baseline.md"]
    assert searched["matches"][0]["path"] == "evidence/baseline.md"
    assert searched["matches"][0]["line"] == 2
    assert read["content"] == "登录超时为 20 秒。\n第三行"
    assert access.files_read == ("evidence/baseline.md",)


def test_agent_tools_reject_writes_escape_and_invalid_arguments(tmp_path) -> None:
    (tmp_path / "draft.md").write_text("当前正文", encoding="utf-8")
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")

    unknown = _execute(access, "write_workspace_file", {"path": "draft.md"})
    escaped = _execute(
        access,
        "read_workspace_file",
        {"path": "../outside.md", "start_line": 1, "line_count": 20},
    )
    malformed = json.loads(access.execute("read_workspace_file", "not-json"))

    assert unknown == {"ok": False, "error": "未知的工作区工具"}
    assert escaped["ok"] is False and "越界" in escaped["error"]
    assert malformed == {"ok": False, "error": "工具参数必须是 JSON 对象"}
    assert access.files_read == ()


def test_agent_read_is_bounded_and_reports_truncation(tmp_path) -> None:
    (tmp_path / "draft.md").write_text("当前正文", encoding="utf-8")
    (tmp_path / "long.md").write_text(
        "\n".join(f"第 {number} 行" for number in range(1, 260)),
        encoding="utf-8",
    )
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")

    result = _execute(
        access,
        "read_workspace_file",
        {"path": "long.md", "start_line": 1, "line_count": 9999},
    )

    assert result["ok"] is True
    assert result["end_line"] == 200
    assert result["truncated"] is True

