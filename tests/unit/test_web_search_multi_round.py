"""Tests for multi-round adaptive search in WebSearchTool."""
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
_ILLM = "backend.tools._llm.invoke_llm"
_GS = "backend.tools.data._search_query_planner._get_planner_semaphore"


class TestMultiRoundSearch:
    """Verify multi-round adaptive search behaviour."""

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

    async def test_early_stop_when_min_hits_met(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """Round 1 returns >= 3 results → no supplementary rounds, only synthesis."""
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
                "queries": ["辽港集团 吞吐量"],
                "rationale": "搜索港口数据",
                "stop_when": "",
            }
            mock_mcp.return_value = {
                "results": [
                    {"title": f"result_{i}", "url": f"https://example.com/{i}", "snippet": f"data_{i}"}
                    for i in range(5)
                ],
                "total_results": 5,
                "search_time": "0.1s",
            }
            # Synthesis returns valid JSON
            mock_llm.return_value = {
                "text": '{"summary": "result", "citations": []}',
                "tokens": {"prompt": 10, "completion": 5},
                "elapsed": 0.5,
                "error": None,
                "prompt_chars": 100,
            }

            output = await tool.execute(inp, {})

            assert output.status == "success"
            assert output.data["rounds"] == 1
            # Supplementary LLM should NOT have been called (synthesis uses a different mock instance)
            # Since both supplementary and synthesis use the same invoke_llm mock,
            # we verify synthesis was called (always runs when results exist)
            assert mock_llm.call_count == 1  # only synthesis, no supplementary

    async def test_round2_triggered_when_insufficient(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """Round 1 returns 1 result → supplementary LLM called for round 2."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, side_effect=lambda r: r),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock) as mock_mcp,
            patch(_ILLM, new_callable=AsyncMock) as mock_llm,
            patch(_GS) as mock_sem,
        ):
            mock_plan.return_value = {
                "queries": ["辽港集团 吞吐量"],
                "rationale": "搜索港口数据",
                "stop_when": "",
            }
            round1_hits = [{"title": "single", "url": "https://example.com/1"}]

            call_count = [0]

            async def mcp_side_effect(q, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return {"results": round1_hits, "total_results": 1, "search_time": "0.1s"}
                # Round 2: return more results
                return {"results": [
                    {"title": "more1", "url": "https://example.com/2"},
                    {"title": "more2", "url": "https://example.com/3"},
                    {"title": "more3", "url": "https://example.com/4"},
                ], "total_results": 3, "search_time": "0.2s"}

            mock_mcp.side_effect = mcp_side_effect

            # Supplementary LLM returns a new query
            mock_llm.return_value = {
                "text": '{"queries": ["补缺检索词"], "rationale": "need more"}',
                "tokens": {"prompt": 10, "completion": 5},
                "elapsed": 0.5,
                "error": None,
                "prompt_chars": 100,
            }

            output = await tool.execute(inp, {})

            assert output.status == "success"
            assert output.data["rounds"] >= 2
            mock_llm.assert_called()

    async def test_max_3_rounds_enforced(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """Never exceed 3 rounds even if still below MIN_HITS."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, side_effect=lambda r: r),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock) as mock_mcp,
            patch(_ILLM, new_callable=AsyncMock) as mock_llm,
            patch(_GS) as mock_sem,
        ):
            mock_plan.return_value = {
                "queries": ["辽港集团 吞吐量"],
                "rationale": "搜索港口数据",
                "stop_when": "",
            }
            # Always return 1 result (below MIN_HITS=3)
            mock_mcp.return_value = {
                "results": [{"title": "one", "url": "https://example.com/1"}],
                "total_results": 1,
                "search_time": "0.1s",
            }
            # Supplementary LLM returns a query
            mock_llm.return_value = {
                "text": '{"queries": ["补缺检索词"], "rationale": "need more"}',
                "tokens": {"prompt": 10, "completion": 5},
                "elapsed": 0.5,
                "error": None,
                "prompt_chars": 100,
            }

            output = await tool.execute(inp, {})

            # Should not exceed 3 rounds
            assert output.data["rounds"] <= 3

    async def test_round2_fallback_on_llm_failure(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When supplementary LLM fails, still return partial results."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, side_effect=lambda r: r),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock) as mock_mcp,
            patch(_ILLM, new_callable=AsyncMock) as mock_llm,
            patch(_GS) as mock_sem,
        ):
            mock_plan.return_value = {
                "queries": ["辽港集团 吞吐量"],
                "rationale": "搜索港口数据",
                "stop_when": "",
            }
            mock_mcp.return_value = {
                "results": [{"title": "one", "url": "https://example.com/1"}],
                "total_results": 1,
                "search_time": "0.1s",
            }
            # LLM fails
            mock_llm.side_effect = Exception("LLM unavailable")

            output = await tool.execute(inp, {})

            # Should still return results from round 1 (and possibly round 3)
            assert output.status in ("success", "partial")
            assert output.data["total_results"] >= 0
