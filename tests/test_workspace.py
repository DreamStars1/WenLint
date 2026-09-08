from __future__ import annotations

from pathlib import Path
from io import BytesIO

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


def test_workspace_rejects_oversized_file_before_opening_it(tmp_path, monkeypatch) -> None:
    target = tmp_path / "large.md"
    target.write_bytes(b"x" * 17)
    workspace = WorkspaceSession(tmp_path)
    monkeypatch.setattr("wenlint.workspace.MAX_WORKSPACE_FILE_BYTES", 16)
    real_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path == target:
            pytest.fail("oversized file must be rejected before opening")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(WorkspaceError, match="超过"):
        workspace.read("large.md")


def test_workspace_caps_read_if_file_grows_after_size_check(tmp_path, monkeypatch) -> None:
    target = tmp_path / "growing.md"
    target.write_bytes(b"small")
    workspace = WorkspaceSession(tmp_path)
    monkeypatch.setattr("wenlint.workspace.MAX_WORKSPACE_FILE_BYTES", 16)
    sizes = []

    class GrowingFile(BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            return super().read(size)

    real_open = Path.open

    def replaced_open(path, *args, **kwargs):
        if path == target:
            return GrowingFile(b"x" * 64)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replaced_open)
    with pytest.raises(WorkspaceError, match="超过"):
        workspace.read("growing.md")
    assert sizes == [17]


def test_workspace_review_context_contains_paths_but_not_sibling_contents(tmp_path) -> None:
    (tmp_path / "draft.md").write_text("当前正文", encoding="utf-8")
    (tmp_path / "private.txt").write_text("不应发送的其他正文", encoding="utf-8")

    context = WorkspaceSession(tmp_path).review_context("draft.md")

    assert "draft.md" in context and "private.txt" in context
    assert "不应发送的其他正文" not in context


def test_workspace_rejects_escape(tmp_path) -> None:
    workspace = WorkspaceSession(tmp_path)
    with pytest.raises(WorkspaceError):
        workspace.read("../outside.md")


def test_workspace_rejects_symlink_root(tmp_path, monkeypatch) -> None:
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == tmp_path or original(path),
    )

    with pytest.raises(WorkspaceError, match="符号链接"):
        WorkspaceSession(tmp_path)


def test_workspace_rejects_symlink_in_root_ancestor(tmp_path, monkeypatch) -> None:
    original = Path.is_symlink
    linked_parent = tmp_path.parent
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == linked_parent or original(path),
    )

    with pytest.raises(WorkspaceError, match="符号链接"):
        WorkspaceSession(tmp_path)


def test_workspace_index_skips_nested_windows_junction(tmp_path, monkeypatch) -> None:
    (tmp_path / "normal").mkdir()
    (tmp_path / "normal" / "included.md").write_text("正文", encoding="utf-8")
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked" / "outside.md").write_text("外部正文", encoding="utf-8")
    original = getattr(Path, "is_junction", lambda path: False)
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda path: path.name == "linked" or original(path),
        raising=False,
    )

    paths = [item["path"] for item in WorkspaceSession(tmp_path).index()]

    assert paths == ["normal/included.md"]


def test_workspace_read_rejects_nested_windows_junction(tmp_path, monkeypatch) -> None:
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "outside.md").write_text("外部正文", encoding="utf-8")
    original = getattr(Path, "is_junction", lambda path: False)
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda path: path == linked or original(path),
        raising=False,
    )
    workspace = WorkspaceSession(tmp_path)

    with pytest.raises(WorkspaceError, match="符号链接"):
        workspace.read("linked/outside.md")


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


def test_workspace_can_clear_a_text_file(tmp_path) -> None:
    target = tmp_path / "draft.md"
    target.write_text("删除全部内容", encoding="utf-8")
    workspace = WorkspaceSession(tmp_path)
    opened = workspace.read("draft.md")

    result = workspace.write("draft.md", "", opened["sha256"], confirmed=True)

    assert target.read_text(encoding="utf-8") == ""
    assert len(result["sha256"]) == 64
