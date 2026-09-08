from __future__ import annotations

import json
import pytest

from wenlint.workspace import WorkspaceSession
from wenlint.workspace_agent import WorkspaceAgentAccess


def _execute(access: WorkspaceAgentAccess, name: str, arguments: dict) -> dict:
    return json.loads(access.execute(name, json.dumps(arguments)))


def test_empty_or_budget_rejected_page_does_not_count_as_reference_observation(tmp_path, monkeypatch):
    (tmp_path / "draft.md").write_text("正文", encoding="utf-8")
    (tmp_path / "facts.md").write_text("可核对的事实" * 100, encoding="utf-8")
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")
    empty = _execute(access, "read_workspace_file", {"path": "facts.md", "start_line": 99})
    assert empty["content"] == "" and access.needs_reference_observation
    monkeypatch.setattr("wenlint.workspace_agent.MAX_TOTAL_TOOL_OUTPUT_CHARS", access._returned_chars + 100)
    rejected = _execute(access, "read_workspace_file", {"path": "facts.md"})
    assert not rejected["ok"] and access.needs_reference_observation


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


def test_agent_read_defaults_to_a_small_page_with_a_line_cursor(tmp_path) -> None:
    (tmp_path / "draft.md").write_text("\n".join(str(index) for index in range(75)), encoding="utf-8")
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")

    page = _execute(access, "read_workspace_file", {"path": "draft.md"})
    assert page["end_line"] == 40
    assert page["last_line_complete"] is True
    assert (page["next_start_line"], page["next_start_char"]) == (41, 0)
    assert len(page["content"].splitlines()) == 40


def test_agent_can_page_through_one_long_line_without_omitting_characters(tmp_path) -> None:
    source = "甲" * 4000 + "乙" * 4000 + "丙" * 1500
    (tmp_path / "draft.md").write_text(source, encoding="utf-8")
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")
    arguments = {"path": "draft.md"}
    pages = []
    while True:
        page = _execute(access, "read_workspace_file", arguments)
        assert page["ok"] is True
        assert len(page["content"]) <= 4000
        pages.append(page["content"])
        if page["next_start_line"] is None:
            assert page["truncated"] is False
            assert page["last_line_complete"] is True
            break
        assert page["end_line"] == 1 and page["last_line_complete"] is False
        assert page["end_char"] == page["next_start_char"]
        arguments.update(start_line=page["next_start_line"], start_char=page["next_start_char"])
        assert len(pages) < 4
    assert "".join(pages) == source


def test_agent_read_cursor_moves_from_partial_line_to_following_lines(tmp_path) -> None:
    (tmp_path / "draft.md").write_text("甲" * 4500 + "\n第二行\n第三行", encoding="utf-8")
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")
    page = _execute(access, "read_workspace_file", {"path": "draft.md", "start_line": 1, "start_char": 4000})
    assert page["content"] == "甲" * 500 + "\n第二行\n第三行"
    assert page["end_line"] == 3 and page["end_char"] == 3
    assert page["next_start_line"] is None
    invalid = _execute(access, "read_workspace_file", {"path": "draft.md", "start_char": 4501})
    assert invalid["ok"] is False


def test_search_snippet_contains_late_match_with_exact_source_coordinates(tmp_path) -> None:
    source = "prefix\r\n" + "甲" * 800 + "基线" + "乙" * 800
    (tmp_path / "draft.md").write_bytes(source.encode("utf-8"))
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")
    result = _execute(access, "search_workspace_text", {"query": "基线"})
    match = result["matches"][0]
    assert "基线" in match["text"] and len(match["text"]) <= 500
    assert (match["line"], match["col"], match["start_char"], match["end_char"]) == (2, 801, 800, 802)
    assert source[match["offset"] : match["offset"] + 2] == "基线"
    assert result["truncated"] is False
    assert result["scanned_files"] == 1


@pytest.mark.parametrize("limit_name,limit", [("MAX_SEARCH_FILES", 1), ("MAX_SEARCH_BYTES", 1)])
def test_search_budget_exhaustion_reports_incomplete_coverage(tmp_path, monkeypatch, limit_name, limit) -> None:
    (tmp_path / "a.md").write_text("没有命中", encoding="utf-8")
    (tmp_path / "draft.md").write_text("目标证据", encoding="utf-8")
    access = WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")
    monkeypatch.setattr("wenlint.workspace_agent." + limit_name, limit)
    result = _execute(access, "search_workspace_text", {"query": "目标证据"})
    assert result["matches"] == []
    assert result["truncated"] is True
    assert result["scanned_files"] < 2
