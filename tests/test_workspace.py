from __future__ import annotations

import pytest

from wenlint.workspace import WorkspaceError, WorkspaceSession


def test_workspace_indexes_supported_text_files_and_ignores_build_dirs(tmp_path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("说明", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("记录", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"png")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "hidden.md").write_text("不要读取", encoding="utf-8")

    workspace = WorkspaceSession(tmp_path)
    paths = [item["path"] for item in workspace.index()]

    assert paths == ["docs/guide.md", "notes.txt"]


def test_workspace_reads_file_and_returns_hash(tmp_path) -> None:
    (tmp_path / "draft.md").write_text("原文", encoding="utf-8")

    result = WorkspaceSession(tmp_path).read("draft.md")

    assert result["content"] == "原文"
    assert result["path"] == "draft.md"
    assert len(result["sha256"]) == 64


def test_workspace_rejects_escape_and_symlink(tmp_path) -> None:
    workspace = WorkspaceSession(tmp_path)
    with pytest.raises(WorkspaceError):
        workspace.read("../outside.md")


def test_workspace_write_requires_matching_hash_and_confirmation(tmp_path) -> None:
    target = tmp_path / "draft.md"
    target.write_text("原文", encoding="utf-8")
    workspace = WorkspaceSession(tmp_path)
    opened = workspace.read("draft.md")

    with pytest.raises(WorkspaceError, match="确认"):
        workspace.write("draft.md", "修改稿", opened["sha256"], confirmed=False)

    target.write_text("外部修改", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="已被其他程序修改"):
        workspace.write("draft.md", "修改稿", opened["sha256"], confirmed=True)


def test_workspace_writes_confirmed_revision_atomically(tmp_path) -> None:
    target = tmp_path / "draft.md"
    target.write_text("原文", encoding="utf-8")
    workspace = WorkspaceSession(tmp_path)
    opened = workspace.read("draft.md")

    result = workspace.write(
        "draft.md", "修改稿", opened["sha256"], confirmed=True
    )

    assert target.read_text(encoding="utf-8") == "修改稿"
    assert result["sha256"] != opened["sha256"]
    assert not (tmp_path / ".draft.md.wenlint.tmp").exists()
