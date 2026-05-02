"""Web Search Skill — 通过 MCP 协议调用 HiAgent 搜索服务，返回结构化搜索结果。
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tracing import make_span

logger = logging.getLogger("analytica.tools.web_search")


@register_tool("tool_web_search", ToolCategory.SEARCH, "互联网检索，返回结构化摘要",
                input_spec="搜索关键词 (query)",
                output_spec="搜索结果 JSON (query/total_results/results[])")
class WebSearchTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        query = inp.params.get("query", "")
        if not query:
            return self._fail("缺少 query 参数")

        # ── 搜索领域上下文增强（Layer 2 兜底）──
        search_prefix = inp.params.get("__search_domain_prefix__", "")
        if search_prefix:
            prefix_keywords = set(search_prefix.split())
            # 如果 LLM 已生成的 query 中已含领域关键词则不追加（避免冗余）
            if not any(kw in query for kw in prefix_keywords):
                query = f"{search_prefix} {query}"

        task_id = inp.params.get("__task_id__", "unknown")
        _start = _time.monotonic()

        # ── 发出搜索调用开始 span ──
        if inp.span_emit:
            await inp.span_emit(make_span(
                "api_call", task_id, status="start",
                input={"query": query, "service": "HiAgent-MCP-Server"},
            ))

        try:
            from backend.tools.data._mcp_client import call_mcp_search

            result = await call_mcp_search(query, timeout=30.0)
            latency_ms = int((_time.monotonic() - _start) * 1000)

            if "error" in result:
                if inp.span_emit:
                    await inp.span_emit(make_span(
                        "api_call", task_id, status="error",
                        output={"error": result["error"], "latency_ms": latency_ms},
                    ))
                return self._fail(result["error"])

            total = result.get("total_results", len(result.get("results", [])))
            results_list = result.get("results", [])

            if inp.span_emit:
                await inp.span_emit(make_span(
                    "api_call", task_id, status="ok",
                    output={"total_results": total, "latency_ms": latency_ms},
                ))

            if not results_list:
                return ToolOutput(
                    tool_id=self.tool_id,
                    status="partial",
                    output_type="json",
                    data={
                        "query": query,
                        "total_results": 0,
                        "results": [],
                    },
                    metadata={
                        "query": query,
                        "total_results": 0,
                        "note": "未找到相关结果",
                    },
                )

            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="json",
                data={
                    "query": result.get("query", query),
                    "search_time": result.get("search_time", ""),
                    "total_results": total,
                    "results": results_list,
                },
                metadata={
                    "query": result.get("query", query),
                    "total_results": total,
                },
            )

        except asyncio.TimeoutError:
            if inp.span_emit:
                await inp.span_emit(make_span(
                    "api_call", task_id, status="error",
                    output={"error": "timeout"},
                ))
            return self._fail("搜索请求超时，请稍后重试")
        except Exception as e:
            logger.exception("WebSearchTool execute error: %s", e)
            if inp.span_emit:
                await inp.span_emit(make_span(
                    "api_call", task_id, status="error",
                    output={"error": str(e)[:200]},
                ))
            return self._fail(f"搜索执行异常: {str(e)[:300]}")
