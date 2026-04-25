"""Tool Registry — singleton registry with @register_tool decorator.

Tools register themselves at import time via the decorator.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.tools.base import BaseTool, ToolCategory

logger = logging.getLogger("analytica.tools.registry")


class ToolRegistry:
    """Singleton tool registry."""

    _instance: Optional[ToolRegistry] = None
    _tools: dict[str, BaseTool]

    def __init__(self) -> None:
        self._tools = {}

    @classmethod
    def get_instance(cls) -> ToolRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def register(self, tool: BaseTool) -> None:
        logger.info("Registering tool: %s", tool.tool_id)
        self._tools[tool.tool_id] = tool

    def get_tool(self, tool_id: str) -> Optional[BaseTool]:
        return self._tools.get(tool_id)

    def list_tools(self, category: Optional[str] = None) -> list[dict]:
        results = []
        for tid, tool in self._tools.items():
            if category and tool.category.value != category:
                continue
            results.append({
                "tool_id": tid,
                "category": tool.category.value,
                "description": tool.description,
            })
        return results

    def get_tools_description(self) -> str:
        lines = []
        for tid, tool in self._tools.items():
            lines.append(f"- {tid} [{tool.category.value}]: {tool.description}")
        return "\n".join(lines)

    @property
    def tool_ids(self) -> set[str]:
        return set(self._tools.keys())


def register_tool(
    tool_id: str,
    category: ToolCategory,
    description: str,
    input_spec: str = "",
    output_spec: str = "",
    planner_visible: bool = True,
):
    """Decorator to register a tool class at import time."""
    def decorator(cls):
        instance = cls()
        instance.tool_id = tool_id
        instance.category = category
        instance.description = description
        instance.input_spec = input_spec
        instance.output_spec = output_spec
        instance.planner_visible = planner_visible
        ToolRegistry.get_instance().register(instance)
        return cls
    return decorator
