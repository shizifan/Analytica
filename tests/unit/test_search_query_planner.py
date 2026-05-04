"""Search query planner unit tests.

Covers:
  * Semaphore lazy-init singleton
  * Prompt template contains layered structure
  * Fallback on invalid / empty / missing JSON from LLM
  * Fallback on LLM call error
  * public_hint passed through to prompt
  * Valid response correctly parsed
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.tools.data._search_query_planner import (
    _LIAGANG_BACKGROUND,
    _USER_PROMPT_TEMPLATE,
    _SYSTEM_PROMPT,
    _get_planner_semaphore,
    _fallback,
    plan_search_queries,
)

pytestmark = pytest.mark.unit


# ── Semaphore ─────────────────────────────────────────────────────


def test_planner_semaphore_is_singleton():
    s1 = _get_planner_semaphore()
    s2 = _get_planner_semaphore()
    assert s1 is s2


# ── Prompt structure ──────────────────────────────────────────────


def test_system_prompt_is_non_empty():
    assert len(_SYSTEM_PROMPT) > 20
    assert "JSON" in _SYSTEM_PROMPT


def test_prompt_contains_layered_context():
    assert "【必备背景】" in _USER_PROMPT_TEMPLATE
    assert "【可选背景：员工领域知识】" in _USER_PROMPT_TEMPLATE
    # Template uses {liagang_background} placeholder (value filled by _LIAGANG_BACKGROUND)
    assert "{liagang_background}" in _USER_PROMPT_TEMPLATE
    assert "queries" in _USER_PROMPT_TEMPLATE
    assert "rationale" in _USER_PROMPT_TEMPLATE
    assert "stop_when" in _USER_PROMPT_TEMPLATE


def test_liagang_background_constant_non_empty():
    assert len(_LIAGANG_BACKGROUND) > 30
    assert "大连港" in _LIAGANG_BACKGROUND
    assert "营口港" in _LIAGANG_BACKGROUND


# ── Fallback ───────────────────────────────────────────────────────


def test_fallback_returns_single_query():
    result = _fallback("测试问题")
    assert result["queries"] == ["测试问题"]
    assert "降级" in result["rationale"]
    assert isinstance(result["stop_when"], str)


def test_fallback_empty_query():
    result = _fallback("")
    assert result["queries"] == [""]


# ── plan_search_queries with mocked LLM ────────────────────────────


@pytest.mark.asyncio
async def test_planner_fallback_on_llm_error():
    """When invoke_llm raises an exception, fallback to raw_query."""
    with patch(
        "backend.tools.data._search_query_planner.invoke_llm",
        side_effect=RuntimeError("simulated LLM failure"),
    ):
        result = await plan_search_queries("辽港集团 2026年 集装箱吞吐量")
        assert result["queries"] == ["辽港集团 2026年 集装箱吞吐量"]
        assert "降级" in result["rationale"]


@pytest.mark.asyncio
async def test_planner_fallback_on_returned_error():
    """When invoke_llm returns an error dict, fallback to raw_query."""
    with patch(
        "backend.tools.data._search_query_planner.invoke_llm",
        new_callable=AsyncMock,
        return_value={"text": "", "error": "network timeout", "error_category": "TIMEOUT"},
    ):
        result = await plan_search_queries("辽港集团 投资分析")
        assert result["queries"] == ["辽港集团 投资分析"]
        assert "降级" in result["rationale"]


@pytest.mark.asyncio
async def test_planner_fallback_on_unparseable_json():
    """When LLM returns unparseable text, fallback."""
    with patch(
        "backend.tools.data._search_query_planner.invoke_llm",
        new_callable=AsyncMock,
        return_value={"text": "这不是 JSON，这是一段解释文字", "error": None},
    ):
        result = await plan_search_queries("辽港集团 生产运营")
        assert result["queries"] == ["辽港集团 生产运营"]
        assert "降级" in result["rationale"]


@pytest.mark.asyncio
async def test_planner_fallback_on_empty_queries():
    """When LLM returns queries=[], fallback."""
    with patch(
        "backend.tools.data._search_query_planner.invoke_llm",
        new_callable=AsyncMock,
        return_value={
            "text": '{"queries": [], "rationale": "无匹配", "stop_when": ""}',
            "error": None,
        },
    ):
        result = await plan_search_queries("辽港集团 数据分析")
        assert result["queries"] == ["辽港集团 数据分析"]
        assert "降级" in result["rationale"]


@pytest.mark.asyncio
async def test_planner_fallback_on_missing_queries_key():
    """When LLM returns JSON without 'queries' key, fallback."""
    with patch(
        "backend.tools.data._search_query_planner.invoke_llm",
        new_callable=AsyncMock,
        return_value={
            "text": '{"rationale": "只给了理由", "stop_when": ""}',
            "error": None,
        },
    ):
        result = await plan_search_queries("辽港集团")
        assert result["queries"] == ["辽港集团"]
        assert "降级" in result["rationale"]


@pytest.mark.asyncio
async def test_planner_valid_response():
    """Normal path: LLM returns valid JSON with queries."""
    with patch(
        "backend.tools.data._search_query_planner.invoke_llm",
        new_callable=AsyncMock,
        return_value={
            "text": '{"queries": ["辽港集团 2026 集装箱吞吐量", "大连港 货物吞吐量 同比"], '
                    '"rationale": "多角度检索", "stop_when": "获取3条以上有效结果"}',
            "error": None,
        },
    ):
        result = await plan_search_queries("分析辽港集团2026年集装箱吞吐量趋势")
        assert len(result["queries"]) == 2
        assert "辽港集团" in result["queries"][0]
        assert result["rationale"] == "多角度检索"
        assert result["stop_when"] == "获取3条以上有效结果"


@pytest.mark.asyncio
async def test_planner_with_public_hint():
    """public_hint should appear in the prompt sent to LLM."""
    captured_prompt: list[str] = []

    async def _fake_invoke(user_prompt, **kwargs):
        captured_prompt.append(user_prompt)
        return {
            "text": '{"queries": ["辽港集团 资产投资"], "rationale": "test", "stop_when": ""}',
            "error": None,
        }

    with patch(
        "backend.tools.data._search_query_planner.invoke_llm",
        new_callable=AsyncMock,
        side_effect=_fake_invoke,
    ):
        await plan_search_queries(
            "资产分析", public_hint="港口设备、资产管理、投资分析"
        )
        assert len(captured_prompt) == 1
        assert "港口设备、资产管理、投资分析" in captured_prompt[0]


@pytest.mark.asyncio
async def test_planner_without_public_hint_shows_default():
    """Without public_hint, prompt should show the default placeholder."""
    captured_prompt: list[str] = []

    async def _fake_invoke(user_prompt, **kwargs):
        captured_prompt.append(user_prompt)
        return {
            "text": '{"queries": ["辽港集团"], "rationale": "test", "stop_when": ""}',
            "error": None,
        }

    with patch(
        "backend.tools.data._search_query_planner.invoke_llm",
        new_callable=AsyncMock,
        side_effect=_fake_invoke,
    ):
        await plan_search_queries("通用分析")
        assert len(captured_prompt) == 1
        assert "（未配置，按通用方式处理）" in captured_prompt[0]


@pytest.mark.asyncio
async def test_planner_empty_raw_query():
    """Empty raw_query should return empty result immediately."""
    result = await plan_search_queries("")
    assert result["queries"] == []
    assert result["rationale"] == ""
