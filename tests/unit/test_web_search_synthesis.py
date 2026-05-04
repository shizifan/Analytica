"""Tests for result synthesis in WebSearchTool."""
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


class TestSynthesis:
    """Verify result synthesis with LLM summary and citations."""

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

    async def test_synthesis_produces_summary_with_citations(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When results exist (>= MIN_HITS), only synthesis LLM fires."""
        plan_result = {
            "queries": ["辽港集团 吞吐量"],
            "rationale": "搜索港口数据",
            "stop_when": "",
        }
        mcp_result = {
            "results": [
                {"title": "2025年港口吞吐量报告", "url": "https://example.com/1",
                 "snippet": "辽港集团2025年吞吐量增长10%"},
                {"title": "营口港运营数据", "url": "https://example.com/2",
                 "snippet": "营口港集装箱吞吐量创新高"},
                {"title": "大连港年度统计", "url": "https://example.com/3",
                 "snippet": "大连港2025年货物吞吐量突破5亿吨"},
            ],
            "total_results": 3,
            "search_time": "0.1s",
        }

        synth_json = (
            '{"summary": "辽港集团2025年吞吐量增长10%[1]，营口港集装箱吞吐量创新高[2]",'
            ' "citations": ['
            '   {"id": 1, "title": "2025年港口吞吐量报告", "url": "https://example.com/1"},'
            '   {"id": 2, "title": "营口港运营数据", "url": "https://example.com/2"}'
            ' ]}'
        )

        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, side_effect=lambda r: r),
            patch(_SAN, side_effect=lambda q: q),
            patch(_GC, return_value=None),
            patch(_SC),
            patch(_MCP, new_callable=AsyncMock, return_value=mcp_result),
            patch(_ILLM, new_callable=AsyncMock) as mock_llm,
            patch(_GS) as mock_sem,
        ):
            mock_plan.return_value = plan_result
            # Synthesis LLM returns valid JSON
            mock_llm.return_value = {
                "text": synth_json,
                "tokens": {"prompt": 50, "completion": 20},
                "elapsed": 0.5,
                "error": None,
                "prompt_chars": 500,
            }

            output = await tool.execute(inp, {})

            assert output.status == "success"
            assert "synthesized_summary" in output.data
            assert "辽港" in output.data["synthesized_summary"]
            assert len(output.data["citations"]) == 2
            # Only synthesis was called (>= MIN_HITS, no supplementary LLM)
            assert mock_llm.call_count == 1

    async def test_synthesis_fallback_on_llm_error(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When synthesis LLM fails, return empty summary but keep raw results."""
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
                "results": [
                    {"title": "test", "url": "https://example.com", "snippet": "data"},
                ],
                "total_results": 1,
                "search_time": "0.1s",
            }
            # Synthesis LLM fails
            mock_llm.side_effect = Exception("LLM unavailable")

            output = await tool.execute(inp, {})

            assert output.status == "success"
            assert output.data["synthesized_summary"] == ""
            assert output.data["citations"] == []
            assert len(output.data["results"]) == 1  # raw results preserved

    async def test_synthesis_empty_results_skips(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When 0 results, synthesis is skipped entirely."""
        with (
            patch(_PSP, new_callable=AsyncMock) as mock_plan,
            patch(_DUP, return_value=[]),
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
            # Return error so has_any_success stays False → no supplementary LLM, no synthesis
            mock_mcp.return_value = {"error": "no results available"}

            output = await tool.execute(inp, {})

            # Synthesis should NOT have been called
            mock_llm.assert_not_called()
            assert output.data["synthesized_summary"] == ""
            assert output.data["citations"] == []

    async def test_synthesis_fallback_on_bad_json(
        self, tool: WebSearchTool, inp: ToolInput,
    ):
        """When LLM returns unparseable JSON, fallback to empty summary."""
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
                "results": [
                    {"title": "test", "url": "https://example.com", "snippet": "data"},
                ],
                "total_results": 1,
                "search_time": "0.1s",
            }
            # LLM returns unparseable text
            mock_llm.return_value = {
                "text": "not valid json at all",
                "tokens": {"prompt": 5, "completion": 3},
                "elapsed": 0.3,
                "error": None,
                "prompt_chars": 100,
            }

            output = await tool.execute(inp, {})

            assert output.status == "success"
            assert output.data["synthesized_summary"] == ""
            assert output.data["citations"] == []
            assert len(output.data["results"]) == 1
