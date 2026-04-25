"""Web Search Skill — searches the web via Tavily API and synthesizes results.

Currently a minimal implementation (Tavily integration is optional).
"""
from __future__ import annotations

from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool


@register_tool("tool_web_search", ToolCategory.SEARCH, "互联网检索，返回结构化摘要",
                input_spec="搜索关键词",
                output_spec="搜索结果摘要文本")
class WebSearchTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        query = inp.params.get("query", "")
        if not query:
            return self._fail("缺少 query 参数")

        # Stub: return a placeholder indicating search is not configured
        return ToolOutput(
            tool_id=self.tool_id,
            status="partial",
            output_type="json",
            data={
                "results": [],
                "synthesized_summary": f"[Web search stub] 搜索关键词: {query}。Tavily API 未配置。",
            },
            metadata={"query": query, "stub": True},
        )
