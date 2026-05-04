"""Tests for empty_reason field in WebSearchTool output."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.tools.base import ToolInput
from backend.tools.data.web_search import WebSearchTool

# ── Correct patch targets: web_search uses delayed imports, so we patch
#    at the actual definition site, not at web_search's module namespace.

_PSP = "backend.tools.data._search_query_planner.plan_search_queries"
_DUP = "backend.tools.data.web_search._dedupe_by_url"
_MCP = "backend.tools.data._mcp_client.call_mcp_search"
_SAN = "backend.tools.data._search_sanitizer.sanitize_query"
_GC  = "backend.tools.data._search_cache.get_cached"
_SC  = "backend.tools.data._search_cache.set_cached"
_ILLM = "backend.tools._llm.invoke_llm"


class TestEmptyReason:
    """Verify empty_reason is correctly set in ToolOutput.data."""

    @pytest.fixture
    def tool(self) -> WebSearchTool:
        return WebSearchTool()

    @pytest.fixture
    def inp(self) -> ToolInput:
        return ToolInput(params={
            "query": "辽港集团 吞吐量",
            "__raw_query__": "辽港集团 吞吐量趋势分析",
            "__search_domain_prefix__": "辽港集团",
            "__search_public_hint__": "",
            "__task_intent__": "分析吞吐量",
        })

    async def test_empty_reason_planner_failed(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When planner returns fallback rationale, empty_reason='planner_failed'."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, return_value=[]),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock) as mock_mcp,
        ):
            mock_plan.return_value = {
                "queries": ["辽港集团"],
                "rationale": "降级回退（LLM 规划失败）",
                "stop_when": "",
            }
            mock_mcp.return_value = {
                "results": [], "total_results": 0, "search_time": "0.1s",
            }

            output = await tool.execute(inp, {})

            assert output.status == "partial"
            assert output.data["empty_reason"] == "planner_failed"
            assert output.metadata["empty_reason"] == "planner_failed"

    async def test_empty_reason_all_mcp_errors(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When all MCP calls return errors, empty_reason='all_mcp_errors'."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, return_value=[]),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock) as mock_mcp,
        ):
            mock_plan.return_value = {
                "queries": ["辽港集团"],
                "rationale": "搜索港口吞吐量数据",
                "stop_when": "",
            }
            mock_mcp.return_value = {"error": "搜索服务异常"}

            output = await tool.execute(inp, {})

            assert output.status == "failed"
            assert output.data["empty_reason"] == "all_mcp_errors"

    async def test_empty_reason_mcp_returned_empty(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When MCP succeeds but returns 0 results, empty_reason='mcp_returned_empty'."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, return_value=[]),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock) as mock_mcp,
        ):
            mock_plan.return_value = {
                "queries": ["辽港集团"],
                "rationale": "搜索港口吞吐量数据",
                "stop_when": "",
            }
            mock_mcp.return_value = {
                "results": [], "total_results": 0, "search_time": "0.1s",
            }

            output = await tool.execute(inp, {})

            assert output.status == "partial"
            assert output.data["empty_reason"] == "mcp_returned_empty"

    async def test_success_path_no_empty_reason(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """Success path should NOT contain empty_reason key."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, side_effect=lambda r: r),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock) as mock_mcp,
            patch(_ILLM, new_callable=AsyncMock) as mock_llm,
        ):
            mock_plan.return_value = {
                "queries": ["辽港集团"],
                "rationale": "搜索港口吞吐量数据",
                "stop_when": "",
            }
            # >= MIN_HITS so supplementary LLM is skipped
            mock_mcp.return_value = {
                "results": [
                    {"title": f"result_{i}", "url": f"https://example.com/{i}"}
                    for i in range(3)
                ],
                "total_results": 3,
                "search_time": "0.1s",
            }
            # Synthesis LLM returns valid JSON
            mock_llm.return_value = {
                "text": '{"summary": "summary", "citations": []}',
                "tokens": {"prompt": 10, "completion": 5},
                "elapsed": 0.5,
                "error": None,
                "prompt_chars": 100,
            }

            output = await tool.execute(inp, {})

            assert output.status == "success"
            assert "empty_reason" not in (output.data or {})
            assert output.data["total_results"] == 3
