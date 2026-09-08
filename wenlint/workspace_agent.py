"""Read-only workspace tools for the desktop review agent.

The model sees only this narrow interface.  Path confinement and output budgets
stay behind the module so neither prompts nor model-supplied arguments can
bypass :class:`WorkspaceSession`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .workspace import WorkspaceError, WorkspaceSession


MAX_LIST_RESULTS = 50
MAX_READ_LINES = 200
MAX_READ_CHARS = 4_000
MAX_SEARCH_FILES = 200
MAX_SEARCH_BYTES = 2 * 1024 * 1024
MAX_SEARCH_RESULTS = 30
MAX_TOTAL_TOOL_OUTPUT_CHARS = 48_000


WORKSPACE_TOOL_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "type": "function",
        "function": {
            "name": "list_workspace_files",
            "description": "按相对路径关键词查找工作区内可审查的文本文件；不返回文件正文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "可选的路径关键词；空字符串表示全部文件。",
                    },
                    "cursor": {"type": "integer", "minimum": 0},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_LIST_RESULTS,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_workspace_text",
            "description": "在工作区文本文件中按字面量搜索，并返回少量命中行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "path_prefix": {
                        "type": "string",
                        "description": "可选的相对目录或路径前缀。",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_RESULTS,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_workspace_file",
            "description": "分页读取工作区文本；默认 40 行，一次最多 200 行或 4000 字符。用返回的 next_start_line 和 next_start_char 继续，长行也可续读。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "start_line": {"type": "integer", "minimum": 1},
                    "start_char": {
                        "type": "integer", "minimum": 0,
                        "description": "首行内从 0 开始的字符偏移；续读时使用 next_start_char。",
                    },
                    "line_count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_READ_LINES,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
)


class WorkspaceAgentAccess:
    """Expose bounded, read-only observations for one selected workspace file."""

    def __init__(self, session: WorkspaceSession, current_path: str) -> None:
        # Validate the current path through the same safe reader used by tools.
        current = session.read(current_path)
        self._session = session
        self._current_path = str(current["path"])
        self._reference_files_available = any(str(item["path"]) != self._current_path for item in session.index())
        self._files_read: list[str] = []
        self._returned_chars = 0

    @property
    def context(self) -> dict[str, object]:
        """Minimal initial context; intentionally excludes the workspace index."""

        return {
            "workspace_name": self._session.name,
            "current_file": self._current_path,
            "reference_files_available": self._reference_files_available,
            "access": "read-only, on demand",
        }

    @property
    def tool_definitions(self) -> tuple[dict[str, object], ...]:
        return WORKSPACE_TOOL_DEFINITIONS

    @property
    def files_read(self) -> tuple[str, ...]:
        return tuple(self._files_read)

    @property
    def needs_reference_observation(self) -> bool:
        """The supplied draft alone cannot verify itself against other files."""
        return self._reference_files_available and not any(path != self._current_path for path in self._files_read)

    def execute(self, name: str, arguments_json: str) -> str:
        """Execute one model-requested tool and return a bounded JSON observation."""

        previously_observed = list(self._files_read)
        try:
            arguments = json.loads(arguments_json)
        except (TypeError, json.JSONDecodeError):
            return self._render({"ok": False, "error": "工具参数必须是 JSON 对象"})
        if not isinstance(arguments, dict):
            return self._render({"ok": False, "error": "工具参数必须是 JSON 对象"})
        try:
            if name == "list_workspace_files":
                result = self._list_files(arguments)
            elif name == "search_workspace_text":
                result = self._search_text(arguments)
            elif name == "read_workspace_file":
                result = self._read_file(arguments)
            else:
                result = {"ok": False, "error": "未知的工作区工具"}
        except (ValueError, WorkspaceError) as exc:
            result = {"ok": False, "error": str(exc)}
        accepted = self._returned_chars + len(json.dumps(result, ensure_ascii=False)) <= MAX_TOTAL_TOOL_OUTPUT_CHARS
        rendered = self._render(result)
        if not accepted:
            self._files_read = previously_observed
        return rendered

    def _list_files(self, arguments: dict[str, Any]) -> dict[str, object]:
        query = _optional_string(arguments, "query").casefold()
        cursor = _bounded_int(arguments, "cursor", default=0, minimum=0, maximum=2_000)
        limit = _bounded_int(
            arguments,
            "limit",
            default=30,
            minimum=1,
            maximum=MAX_LIST_RESULTS,
        )
        files = [
            item
            for item in self._session.index()
            if not query or query in str(item["path"]).casefold()
        ]
        page = files[cursor : cursor + limit]
        next_cursor = cursor + len(page)
        return {
            "ok": True,
            "files": page,
            "next_cursor": next_cursor if next_cursor < len(files) else None,
            "total_matches": len(files),
        }

    def _search_text(self, arguments: dict[str, Any]) -> dict[str, object]:
        query = _required_string(arguments, "query", "搜索词")
        prefix = _optional_string(arguments, "path_prefix").replace("\\", "/")
        if prefix.startswith("/") or ".." in prefix.split("/"):
            raise WorkspaceError("工作区文件路径越界")
        limit = _bounded_int(
            arguments,
            "limit",
            default=20,
            minimum=1,
            maximum=MAX_SEARCH_RESULTS,
        )
        matches: list[dict[str, object]] = []
        inspected_files = 0
        inspected_bytes = 0
        scanned_files = 0
        skipped_files = 0
        truncated = False
        pattern = re.compile(re.escape(query), re.IGNORECASE)

        def result() -> dict[str, object]:
            return {"ok": True, "matches": matches, "truncated": truncated,
                    "scanned_files": scanned_files, "scanned_bytes": inspected_bytes,
                    "skipped_files": skipped_files}

        for item in self._session.index():
            path = str(item["path"])
            if prefix and not path.startswith(prefix):
                continue
            size = int(item["size"])
            if inspected_files >= MAX_SEARCH_FILES or inspected_bytes + size > MAX_SEARCH_BYTES:
                truncated = True
                break
            inspected_files += 1
            inspected_bytes += size
            try:
                content = str(self._session.read(path)["content"])
            except WorkspaceError:
                skipped_files += 1
                truncated = True
                continue
            scanned_files += 1
            offset = 0
            for line_number, raw_line in enumerate(content.splitlines(keepends=True), 1):
                line = raw_line.splitlines()[0]
                match = pattern.search(line)
                line_offset = offset
                offset += len(raw_line)
                if match is None:
                    continue
                snippet_start = max(0, min(match.start() - 150, len(line) - 500))
                snippet_end = min(len(line), snippet_start + 500)
                matches.append(
                    {
                        "path": path,
                        "line": line_number,
                        "col": match.start() + 1,
                        "start_char": match.start(),
                        "end_char": match.end(),
                        "offset": line_offset + match.start(),
                        "text": line[snippet_start:snippet_end],
                        "snippet_start_char": snippet_start,
                        "snippet_end_char": snippet_end,
                    }
                )
                self._record_read(path)
                if len(matches) >= limit:
                    truncated = True
                    return result()
        return result()

    def _read_file(self, arguments: dict[str, Any]) -> dict[str, object]:
        path = _required_string(arguments, "path", "工作区文件路径")
        start_line = _bounded_int(
            arguments, "start_line", default=1, minimum=1, maximum=10_000_000
        )
        start_char = _bounded_int(
            arguments, "start_char", default=0, minimum=0, maximum=10_000_000
        )
        line_count = _bounded_int(
            arguments,
            "line_count",
            default=40,
            minimum=1,
            maximum=MAX_READ_LINES,
            clamp=True,
        )
        opened = self._session.read(path)
        normalized_path = str(opened["path"])
        lines = str(opened["content"]).splitlines()
        start_index = min(start_line - 1, len(lines))
        if start_char and (start_index >= len(lines) or start_char > len(lines[start_index])):
            raise ValueError("start_char 超出首行字符范围")
        pieces: list[str] = []
        used = 0
        end_line = start_index
        end_char = 0
        next_line: int | None = None
        next_char: int | None = None
        for index in range(start_index, min(start_index + line_count, len(lines))):
            char_offset = start_char if index == start_index else 0
            remaining = MAX_READ_CHARS - used - (1 if pieces else 0)
            if remaining <= 0:
                next_line, next_char = index + 1, char_offset
                break
            piece = lines[index][char_offset : char_offset + remaining]
            used += len(piece) + (1 if pieces else 0)
            pieces.append(piece)
            end_line, end_char = index + 1, char_offset + len(piece)
            if end_char < len(lines[index]):
                next_line, next_char = end_line, end_char
                break
            if index + 1 < len(lines):
                next_line, next_char = index + 2, 0
            else:
                next_line, next_char = None, None
        content = "\n".join(pieces)
        if content.strip():
            self._record_read(normalized_path)
        return {
            "ok": True,
            "path": normalized_path,
            "start_line": start_index + 1 if lines else 0,
            "start_char": start_char,
            "end_line": end_line,
            "end_char": end_char,
            "last_line_complete": not pieces or end_char == len(lines[end_line - 1]),
            "total_lines": len(lines),
            "content": content,
            "truncated": next_line is not None,
            "next_start_line": next_line,
            "next_start_char": next_char,
        }

    def _record_read(self, path: str) -> None:
        if path not in self._files_read:
            self._files_read.append(path)

    def _render(self, value: dict[str, object]) -> str:
        rendered = json.dumps(value, ensure_ascii=False)
        if self._returned_chars + len(rendered) > MAX_TOTAL_TOOL_OUTPUT_CHARS:
            rendered = json.dumps(
                {"ok": False, "error": "工作区工具累计输出已达到上限"},
                ensure_ascii=False,
            )
        self._returned_chars += len(rendered)
        return rendered


def _required_string(arguments: dict[str, Any], key: str, label: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    return value.strip()


def _optional_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须是文本")
    return value.strip()


def _bounded_int(
    arguments: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
    clamp: bool = False,
) -> int:
    value = arguments.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} 必须是整数")
    if clamp:
        return max(minimum, min(value, maximum))
    if value < minimum or value > maximum:
        raise ValueError(f"{key} 超出允许范围")
    return value
