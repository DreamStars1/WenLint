"""Read-only workspace tools for the desktop review agent.

The model sees only this narrow interface.  Path confinement and output budgets
stay behind the module so neither prompts nor model-supplied arguments can
bypass :class:`WorkspaceSession`.
"""

from __future__ import annotations

import json
from typing import Any

from .workspace import WorkspaceError, WorkspaceSession


MAX_LIST_RESULTS = 50
MAX_READ_LINES = 200
MAX_READ_CHARS = 12_000
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
            "description": "按行读取一个工作区文本文件；一次最多返回 200 行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "start_line": {"type": "integer", "minimum": 1},
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
        self._files_read: list[str] = []
        self._returned_chars = 0

    @property
    def context(self) -> dict[str, object]:
        """Minimal initial context; intentionally excludes the workspace index."""

        return {
            "workspace_name": self._session.name,
            "current_file": self._current_path,
            "access": "read-only, on demand",
        }

    @property
    def tool_definitions(self) -> tuple[dict[str, object], ...]:
        return WORKSPACE_TOOL_DEFINITIONS

    @property
    def files_read(self) -> tuple[str, ...]:
        return tuple(self._files_read)

    def execute(self, name: str, arguments_json: str) -> str:
        """Execute one model-requested tool and return a bounded JSON observation."""

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
        return self._render(result)

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
        for item in self._session.index():
            path = str(item["path"])
            if prefix and not path.startswith(prefix):
                continue
            size = int(item["size"])
            if inspected_files >= MAX_SEARCH_FILES or inspected_bytes + size > MAX_SEARCH_BYTES:
                break
            inspected_files += 1
            inspected_bytes += size
            try:
                content = str(self._session.read(path)["content"])
            except WorkspaceError:
                continue
            for line_number, line in enumerate(content.splitlines(), 1):
                if query.casefold() not in line.casefold():
                    continue
                matches.append(
                    {
                        "path": path,
                        "line": line_number,
                        "text": line[:500],
                    }
                )
                self._record_read(path)
                if len(matches) >= limit:
                    return {
                        "ok": True,
                        "matches": matches,
                        "truncated": True,
                    }
        return {"ok": True, "matches": matches, "truncated": False}

    def _read_file(self, arguments: dict[str, Any]) -> dict[str, object]:
        path = _required_string(arguments, "path", "工作区文件路径")
        start_line = _bounded_int(
            arguments, "start_line", default=1, minimum=1, maximum=10_000_000
        )
        line_count = _bounded_int(
            arguments,
            "line_count",
            default=120,
            minimum=1,
            maximum=MAX_READ_LINES,
            clamp=True,
        )
        opened = self._session.read(path)
        normalized_path = str(opened["path"])
        lines = str(opened["content"]).splitlines()
        start_index = min(start_line - 1, len(lines))
        selected = lines[start_index : start_index + line_count]
        content = "\n".join(selected)
        char_truncated = len(content) > MAX_READ_CHARS
        if char_truncated:
            content = content[:MAX_READ_CHARS] + "\n…（内容已截断）"
        end_line = start_index + len(selected)
        self._record_read(normalized_path)
        return {
            "ok": True,
            "path": normalized_path,
            "start_line": start_index + 1 if lines else 0,
            "end_line": end_line,
            "total_lines": len(lines),
            "content": content,
            "truncated": char_truncated or end_line < len(lines),
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
