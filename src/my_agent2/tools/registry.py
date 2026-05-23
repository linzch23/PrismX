from __future__ import annotations

from typing import Any

from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._definitions_cache: list[dict[str, Any]] | None = None

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self._definitions_cache = None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def definitions(self) -> list[dict[str, Any]]:
        if self._definitions_cache is not None:
            return self._definitions_cache
        self._definitions_cache = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for _, tool in sorted(self._tools.items())
        ]
        return self._definitions_cache

    def execute(self, name: str, params: Any) -> str:
        if not isinstance(params, dict):
            return f"Error: tool {name!r} expected object params, got {type(params).__name__}"
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool {name!r}. Available tools: {', '.join(self.names())}"
        try:
            cast = tool.cast_params(params)
            tool.validate_params(cast)
            return tool.execute(**cast)
        except Exception as exc:
            return f"Error executing {name}: {exc}"
