"""Tool descriptions — 从运行时 ToolRegistry 动态生成。

供规划层 Prompt 注入。不再维护静态 dict，所有工具元数据来自 @register_tool。
"""
from __future__ import annotations

from typing import Optional


def get_tools_description(allowed_tools: Optional[frozenset[str]] = None) -> str:
    """从运行时 ToolRegistry 动态生成规划层工具描述。

    Args:
        allowed_tools: 工具 ID 白名单；None 表示不过滤。
    """
    from backend.tools.registry import ToolRegistry
    registry = ToolRegistry.get_instance()
    lines: list[str] = []
    for tid, tool in registry._tools.items():
        if not tool.planner_visible:
            continue
        if allowed_tools is not None and tid not in allowed_tools:
            continue
        lines.append(f"- {tid}: {tool.description}")
        if tool.input_spec or tool.output_spec:
            lines.append(f"  输入: {tool.input_spec} → 输出: {tool.output_spec}")
    return "\n".join(lines)


def get_valid_tool_ids(allowed_tools: Optional[frozenset[str]] = None) -> set[str]:
    """从运行时注册表获取合法工具 ID 集合。"""
    from backend.tools.registry import ToolRegistry
    all_ids = ToolRegistry.get_instance().tool_ids
    if allowed_tools is not None:
        return all_ids & allowed_tools
    return all_ids


def is_valid_tool(tool_id: str) -> bool:
    """检查工具 ID 是否在运行时注册表中。"""
    from backend.tools.registry import ToolRegistry
    return tool_id in ToolRegistry.get_instance().tool_ids
