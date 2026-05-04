"""Tests for provider timeout layering in web_search."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.tools.base import ToolInput
from backend.tools.data.web_search import WebSearchTool

_PSP = "backend.tools.data._search_query_planner.plan_search_queries"
_DUP = "backend.tools.data.web_search._dedupe_by_url"
_MCP = "backend.tools.data._mcp_client.call_mcp_search"
_SAN = "backend.tools.data._search_sanitizer.sanitize_query"
_GC  = "backend.tools.data._search_cache.get_cached"
_SC  = "backend.tools.data._search_cache.set_cached"
_GS  = "backend.config.get_settings"


class TestProviderTimeout:
    """Verify MCP timeout uses config and fast-fail detection works."""

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
            "__task_id__": "test_task",
        })

    async def test_search_one_fast_fail_on_mcp_error(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When call_mcp_search returns error dict, _search_one returns ok=False."""
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
                "rationale": "搜索港口数据",
                "stop_when": "",
            }
            mock_mcp.return_value = {"error": "搜索服务异常: connection refused"}

            output = await tool.execute(inp, {})

            assert output.data["total_results"] == 0
            assert output.metadata["empty_reason"] == "all_mcp_errors"

    async def test_provider_timeout_from_config(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """Verify SEARCH_PROVIDER_TIMEOUT config is respected."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_GS) as mock_settings,
            patch(_DUP, side_effect=lambda r: r),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock) as mock_mcp,
        ):
            mock_settings.return_value.SEARCH_PROVIDER_TIMEOUT = 45.0
            mock_plan.return_value = {
                "queries": ["辽港集团"],
                "rationale": "搜索港口数据",
                "stop_when": "",
            }
            mock_mcp.return_value = {
                "results": [{"title": "test", "url": "https://example.com"}],
                "total_results": 1,
                "search_time": "0.1s",
            }

            await tool.execute(inp, {})

            mock_mcp.assert_called_once()
            call_kwargs = mock_mcp.call_args.kwargs
            assert call_kwargs["timeout"] == 45.0
