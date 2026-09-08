"""Constrained workspace access for the desktop application.

The desktop bridge owns one explicitly selected root.  Every read and write is
resolved relative to that root, ignores generated/vendor directories, rejects
symlinks, and uses an optimistic content hash before replacing a file.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path


MAX_WORKSPACE_FILES = 2_000
MAX_WORKSPACE_FILE_BYTES = 2 * 1024 * 1024
MAX_WORKSPACE_CONTEXT_CHARS = 30_000
SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".mdx", ".rst", ".txt"})
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "vendor",
    }
)


class WorkspaceError(RuntimeError):
    """A safe, user-facing workspace operation failure."""


class WorkspaceSession:
    """Read and update supported text files below one user-selected root."""

    def __init__(self, root: str | Path) -> None:
        requested = Path(root)
        absolute = Path(os.path.abspath(requested))
        if any(_is_link(path) for path in (absolute, *absolute.parents)):
            raise WorkspaceError("工作区根目录不能是符号链接或目录联接")
        resolved = requested.resolve(strict=True)
        if not resolved.is_dir():
            raise WorkspaceError("所选工作区不是目录")
        self.root = resolved

    @property
    def name(self) -> str:
        return self.root.name or str(self.root)

    def index(self) -> list[dict[str, object]]:
        """Return a stable, content-free manifest for supported files."""

        files: list[dict[str, object]] = []
        for directory, dirnames, filenames in os.walk(self.root, followlinks=False):
            current = Path(directory)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not self._ignore_directory(current / name)
            )
            for name in sorted(filenames):
                candidate = current / name
                if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                if candidate.is_symlink():
                    continue
                try:
                    size = candidate.stat().st_size
                    relative = candidate.relative_to(self.root).as_posix()
                except (OSError, ValueError):
                    continue
                files.append({"path": relative, "name": name, "size": size})
                if len(files) >= MAX_WORKSPACE_FILES:
                    return sorted(files, key=lambda item: str(item["path"]))
        return sorted(files, key=lambda item: str(item["path"]))

    def read(self, relative_path: str) -> dict[str, object]:
        target = self._resolve_file(relative_path)
        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise WorkspaceError(f"无法读取工作区文件（{type(exc).__name__}）") from None
        if len(raw) > MAX_WORKSPACE_FILE_BYTES:
            raise WorkspaceError("工作区文件超过 2 MB，请拆分后再处理")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise WorkspaceError("工作区文件不是 UTF-8 文本") from None
        return {
            "path": target.relative_to(self.root).as_posix(),
            "filename": target.name,
            "content": content,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    def write(
        self,
        relative_path: str,
        text: str,
        expected_sha256: str,
        *,
        confirmed: bool,
    ) -> dict[str, object]:
        if not confirmed:
            raise WorkspaceError("写回工作区前必须由用户明确确认")
        if not isinstance(text, str):
            raise WorkspaceError("待写回内容必须是文本")
        target = self._resolve_file(relative_path)
        try:
            current = target.read_bytes()
        except OSError as exc:
            raise WorkspaceError(f"无法读取工作区文件（{type(exc).__name__}）") from None
        if hashlib.sha256(current).hexdigest() != expected_sha256:
            raise WorkspaceError("文件已被其他程序修改，请重新打开后再写回")

        encoded = text.encode("utf-8")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.wenlint-",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
            temporary_path = None
        except OSError as exc:
            raise WorkspaceError(f"写回失败（{type(exc).__name__}）") from None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return {
            "path": target.relative_to(self.root).as_posix(),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }

    def review_context(self, relative_path: str) -> str:
        """Describe the selected file's position without reading sibling content."""

        selected = self._resolve_file(relative_path).relative_to(self.root).as_posix()
        lines: list[str] = []
        used = 0
        for item in self.index():
            line = f"- {item['path']}"
            if used + len(line) + 1 > MAX_WORKSPACE_CONTEXT_CHARS:
                lines.append("- …（其余路径已省略）")
                break
            lines.append(line)
            used += len(line) + 1
        rendered = "\n".join(lines)
        return (
            f"工作区名称：{self.name}\n"
            f"当前文件：{selected}\n"
            "工作区文本文件索引（仅路径，未附带其他文件正文）：\n"
            f"{rendered}"
        )

    def _ignore_directory(self, path: Path) -> bool:
        return (
            path.name in IGNORED_DIRECTORIES
            or path.name.startswith(".")
            or _is_link(path)
        )

    def _resolve_file(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise WorkspaceError("工作区文件路径不能为空")
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkspaceError("工作区文件路径越界")
        candidate = self.root / relative
        if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise WorkspaceError("该文件类型不支持文本审查")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.root)
        except (OSError, ValueError):
            raise WorkspaceError("工作区文件不存在或路径越界") from None
        if not resolved.is_file() or _is_link(candidate):
            raise WorkspaceError("工作区目标不是普通文件")
        parent = candidate.parent
        while parent != self.root:
            if _is_link(parent):
                raise WorkspaceError("工作区不读取符号链接")
            parent = parent.parent
        return resolved


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", lambda: False)
    if path.is_symlink() or is_junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_point)
