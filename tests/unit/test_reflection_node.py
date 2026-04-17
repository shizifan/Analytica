"""Tests for Reflection Node — Phase 4 Sprint 10.

TC-RF01 ~ TC-RF07: LLM extraction, degradation, card format, parallel execution.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.agent.reflection import (
    call_llm_a,
    call_llm_b,
    format_reflection_card,
    reflection_node,
    _strip_think_tags,
    _extract_json,
)


# ── Helper: Build test states ────────────────────────────────


def _make_base_state(**overrides) -> dict:
    """Create a base AgentState-like dict for reflection tests."""
    state = {
        "session_id": "test-session-001",
        "user_id": "test-user-001",
        "messages": [
            {"role": "user", "content": "分析一下今年Q1港口集装箱吞吐量的变化趋势"},
            {"role": "assistant", "content": "已理解您的分析需求"},
        ],
        "slots": {
            "analysis_subject": {"value": ["集装箱吞吐量"], "source": "user_input", "confirmed": True},
            "time_range": {"value": {"start": "2026-01-01", "end": "2026-03-31"}, "source": "user_input", "confirmed": True},
            "output_complexity": {"value": "chart_text", "source": "inferred", "confirmed": False},
            "time_granularity": {"value": "monthly", "source": "inferred", "confirmed": False},
        },
        "analysis_plan": {
            "tasks": [
                {"task_id": "T001", "type": "data_fetch", "name": "获取吞吐量数据", "skill": "skill_api_fetch", "estimated_seconds": 10},
                {"task_id": "T002", "type": "analysis", "name": "描述性分析", "skill": "skill_desc_analysis", "estimated_seconds": 15},
                {"task_id": "T003", "type": "visualization", "name": "折线图", "skill": "skill_chart_line", "estimated_seconds": 5},
            ],
        },
        "task_statuses": {"T001": "done", "T002": "done", "T003": "done"},
        "execution_context": {},
        "current_phase": "execution",
    }
    state.update(overrides)
    return state


def make_completed_session_state(output_format_used: str = "chart_text") -> dict:
    """State with explicit output format used."""
    return _make_base_state(
        slots={
            "analysis_subject": {"value": ["集装箱吞吐量"], "source": "user_input", "confirmed": True},
            "time_range": {"value": {"start": "2026-01-01", "end": "2026-03-31"}, "source": "user_input", "confirmed": True},
            "output_complexity": {"value": output_format_used, "source": "user_input", "confirmed": True},
            "time_granularity": {"value": "monthly", "source": "inferred", "confirmed": False},
        }
    )


def make_simple_query_state() -> dict:
    """Simple table + 1 task state."""
    return _make_base_state(
        slots={
            "analysis_subject": {"value": ["吞吐量"], "source": "user_input", "confirmed": True},
            "time_range": {"value": {"start": "2026-03-01", "end": "2026-03-31"}, "source": "user_input", "confirmed": True},
            "output_complexity": {"value": "simple_table", "source": "inferred", "confirmed": False},
        },
        analysis_plan={
            "tasks": [
                {"task_id": "T001", "type": "data_fetch", "name": "获取数据", "skill": "skill_api_fetch", "estimated_seconds": 10},
            ],
        },
        task_statuses={"T001": "done"},
    )


def make_full_report_state() -> dict:
    """Full report state with multiple tasks."""
    return _make_base_state(
        slots={
            "analysis_subject": {"value": ["港口运营分析"], "source": "user_input", "confirmed": True},
            "time_range": {"value": {"start": "2026-01-01", "end": "2026-03-31"}, "source": "user_input", "confirmed": True},
            "output_complexity": {"value": "full_report", "source": "user_input", "confirmed": True},
            "output_format": {"value": "pptx", "source": "user_input", "confirmed": True},
            "time_granularity": {"value": "monthly", "source": "inferred", "confirmed": False},
        },
        analysis_plan={
            "tasks": [
                {"task_id": "T001", "type": "data_fetch", "name": "获取吞吐量", "skill": "skill_api_fetch", "estimated_seconds": 10},
                {"task_id": "T002", "type": "data_fetch", "name": "获取泊位", "skill": "skill_api_fetch", "estimated_seconds": 10},
                {"task_id": "T003", "type": "analysis", "name": "描述性分析", "skill": "skill_desc_analysis", "estimated_seconds": 15},
                {"task_id": "T004", "type": "analysis", "name": "归因分析", "skill": "skill_attribution", "estimated_seconds": 20},
                {"task_id": "T005", "type": "visualization", "name": "折线图", "skill": "skill_chart_line", "estimated_seconds": 5},
                {"task_id": "T006", "type": "report_gen", "name": "生成PPT", "skill": "skill_report_pptx", "estimated_seconds": 30},
            ],
        },
        task_statuses={"T001": "done", "T002": "done", "T003": "done", "T004": "done", "T005": "done", "T006": "done"},
    )


def make_state_with_slot_correction(slot_name: str, from_val: str, to_val: str) -> dict:
    """State where a slot was corrected by the user."""
    state = _make_base_state()
    state["messages"] = [
        {"role": "user", "content": "分析一下吞吐量"},
        {"role": "assistant", "content": f"确认 {slot_name}={from_val}？"},
        {"role": "user", "content": f"不，改为 {to_val}"},
        {"role": "assistant", "content": f"已更新为 {to_val}"},
    ]
    state["slots"][slot_name] = {"value": to_val, "source": "user_input", "confirmed": True}
    return state


# ── Mock LLM responses ──────────────────────────────────────

MOCK_LLM_A_BASIC = json.dumps({
    "user_preferences": {
        "output_format": "pptx",
        "time_granularity": "monthly",
        "chart_types": ["line"],
        "analysis_depth": {"attribution": True, "predictive": False},
        "domain_terms": {},
    },
    "analysis_template": None,
    "slot_quality_review": {
        "slots_auto_filled_correctly": ["time_granularity"],
        "slots_corrected": [],
        "slots_corrected_detail": {},
    },
})

MOCK_LLM_A_WITH_TEMPLATE = json.dumps({
    "user_preferences": {"output_format": "pptx"},
    "analysis_template": {
        "template_name": "月度港口运营分析",
        "applicable_scenario": "月度各业务板块吞吐量趋势与归因分析",
        "plan_skeleton": {"tasks": [{"type": "data_fetch"}, {"type": "analysis"}, {"type": "report_gen"}]},
    },
    "slot_quality_review": {
        "slots_auto_filled_correctly": ["time_granularity", "output_format"],
        "slots_corrected": [],
        "slots_corrected_detail": {},
    },
})

MOCK_LLM_A_CORRECTED = json.dumps({
    "user_preferences": {},
    "analysis_template": None,
    "slot_quality_review": {
        "slots_auto_filled_correctly": ["time_granularity"],
        "slots_corrected": ["output_complexity"],
        "slots_corrected_detail": {
            "output_complexity": {"from": "simple_table", "to": "chart_text"},
        },
    },
})

MOCK_LLM_A_SIMPLE = json.dumps({
    "user_preferences": {"output_format": "simple_table"},
    "analysis_template": None,
    "slot_quality_review": {
        "slots_auto_filled_correctly": [],
        "slots_corrected": [],
        "slots_corrected_detail": {},
    },
})

MOCK_LLM_B_BASIC = json.dumps({
    "skill_feedback": {
        "well_performed": ["skill_api_fetch", "skill_chart_line"],
        "issues_found": [{"skill": "skill_desc_analysis", "issue": "叙述未突出异常月份"}],
        "suggestions": ["在 narrative prompt 中要求指出异常值"],
    },
})


class MockReflectionLLM:
    """Mock LLM that returns different responses based on prompt keywords."""

    def __init__(self):
        self._response_a: str | None = None
        self._response_b: str | None = None

    def set_a(self, resp: str) -> None:
        self._response_a = resp

    def set_b(self, resp: str) -> None:
        self._response_b = resp

    async def ainvoke(self, prompt: str | Any) -> Any:
        text = str(prompt) if not isinstance(prompt, str) else prompt

        class Msg:
            def __init__(self, content):
                self.content = content

        if "偏好" in text or "模板" in text or "槽位" in text:
            return Msg(self._response_a or MOCK_LLM_A_BASIC)
        elif "技能" in text or "评审" in text:
            return Msg(self._response_b or MOCK_LLM_B_BASIC)
        return Msg(MOCK_LLM_A_BASIC)


# ── TC-RF01: Preference extraction includes output_format ────

@pytest.mark.asyncio
async def test_reflection_extracts_output_format():
    """TC-RF01: Verify reflection LLM call A extracts output_format preference."""
    llm = MockReflectionLLM()
    llm.set_a(MOCK_LLM_A_BASIC)
    state = make_completed_session_state(output_format_used="pptx")
    result_a = await call_llm_a(llm, state)
    assert result_a is not None
    prefs = result_a.get("user_preferences", {})
    assert prefs.get("output_format") == "pptx"


# ── TC-RF02: No template for trivial query ───────────────────

@pytest.mark.asyncio
async def test_reflection_no_template_for_trivial_query():
    """TC-RF02: Verify simple query does not generate a reusable template."""
    llm = MockReflectionLLM()
    llm.set_a(MOCK_LLM_A_SIMPLE)
    state = make_simple_query_state()
    result_a = await call_llm_a(llm, state)
    assert result_a is not None
    assert result_a.get("analysis_template") is None


# ── TC-RF03: Complex analysis generates template skeleton ────

@pytest.mark.asyncio
async def test_reflection_generates_template_for_complex_analysis():
    """TC-RF03: Verify full_report analysis generates reusable template skeleton."""
    llm = MockReflectionLLM()
    llm.set_a(MOCK_LLM_A_WITH_TEMPLATE)
    state = make_full_report_state()
    result_a = await call_llm_a(llm, state)
    assert result_a is not None
    template = result_a.get("analysis_template")
    assert template is not None
    assert "template_name" in template
    assert len(template["plan_skeleton"]["tasks"]) >= 3


# ── TC-RF04: Corrected slots identified ──────────────────────

@pytest.mark.asyncio
async def test_reflection_identifies_corrected_slots():
    """TC-RF04: Verify LLM correctly identifies corrected slots."""
    llm = MockReflectionLLM()
    llm.set_a(MOCK_LLM_A_CORRECTED)
    state = make_state_with_slot_correction("output_complexity", "simple_table", "chart_text")
    result_a = await call_llm_a(llm, state)
    assert result_a is not None
    assert "output_complexity" in result_a["slot_quality_review"]["slots_corrected"]


# ── TC-RF05: Reflection card Markdown format ─────────────────

@pytest.mark.asyncio
async def test_reflection_card_markdown_format():
    """TC-RF05: Verify reflection card contains preference/template/feedback sections."""
    reflection_summary = {
        "user_preferences": {"output_format": "pptx", "time_granularity": "monthly"},
        "analysis_template": {
            "template_name": "月度分析",
            "applicable_scenario": "月度吞吐量分析",
            "plan_skeleton": {"tasks": []},
        },
        "skill_feedback": {
            "well_performed": ["skill_api_fetch"],
            "issues_found": [{"skill": "skill_desc_analysis", "issue": "叙述不够"}],
            "suggestions": [],
        },
        "slot_quality_review": {
            "slots_auto_filled_correctly": [],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        },
    }
    card = format_reflection_card(reflection_summary)
    # Card should contain key sections
    assert "偏好" in card or "输出格式" in card
    assert "保存" in card or "全部保存" in card
    assert "月度分析" in card  # Template name
    assert "skill_api_fetch" in card  # Skill feedback


# ── TC-RF06: Think tag stripping before JSON parse ───────────

@pytest.mark.asyncio
async def test_reflection_strips_think_tags():
    """TC-RF06: Verify <think> blocks are stripped before JSON parsing."""
    raw = "<think>分析用户偏好...</think>\n" + json.dumps({
        "user_preferences": {"output_format": "pptx"},
        "analysis_template": None,
        "slot_quality_review": {
            "slots_auto_filled_correctly": [],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        },
    })
    llm = MockReflectionLLM()
    llm.set_a(raw)
    state = make_simple_query_state()
    result_a = await call_llm_a(llm, state)
    assert result_a is not None
    assert result_a["user_preferences"]["output_format"] == "pptx"


# ── TC-RF07: Two LLM calls run in parallel ──────────────────

def _mock_settings():
    """Create a mock settings object."""
    class FakeSettings:
        QWEN_API_BASE = "http://fake"
        QWEN_API_KEY = "fake-key"
        QWEN_MODEL = "fake-model"
    return FakeSettings()


@pytest.mark.asyncio
async def test_reflection_llm_calls_parallel():
    """TC-RF07: Verify LLM-A and LLM-B run concurrently via asyncio.gather."""
    call_records = []

    async def slow_llm_a(llm, state, **kw):
        start = time.time()
        await asyncio.sleep(0.5)
        call_records.append(("A", time.time() - start))
        return json.loads(MOCK_LLM_A_BASIC)

    async def slow_llm_b(llm, state, **kw):
        start = time.time()
        await asyncio.sleep(0.5)
        call_records.append(("B", time.time() - start))
        return json.loads(MOCK_LLM_B_BASIC)

    with patch("backend.agent.reflection.call_llm_a", side_effect=slow_llm_a), \
         patch("backend.agent.reflection.call_llm_b", side_effect=slow_llm_b), \
         patch("langchain_openai.ChatOpenAI", return_value=MockReflectionLLM()), \
         patch("backend.config.get_settings", return_value=_mock_settings()):
        state = make_full_report_state()
        start = time.time()
        result = await reflection_node(state)
        total = time.time() - start

    # Parallel: total should be ~0.5s, not ~1.0s
    assert total < 1.5, f"Expected parallel execution < 1.5s, got {total:.2f}s"


# ── Additional tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_llm_a_partial_failure_returns_none():
    """Verify call_llm_a returns None when LLM consistently returns invalid JSON."""
    class BadLLM:
        async def ainvoke(self, prompt):
            class Msg:
                content = "这不是有效的JSON"
            return Msg()

    result = await call_llm_a(BadLLM(), _make_base_state())
    assert result is None


@pytest.mark.asyncio
async def test_call_llm_b_exception_returns_none():
    """Verify call_llm_b returns None when LLM raises exception."""
    class ErrorLLM:
        async def ainvoke(self, prompt):
            raise RuntimeError("LLM service unavailable")

    result = await call_llm_b(ErrorLLM(), _make_base_state())
    assert result is None


@pytest.mark.asyncio
async def test_reflection_node_both_fail_graceful():
    """Verify reflection node degrades gracefully when both LLM calls fail."""
    with patch("backend.agent.reflection.call_llm_a", side_effect=Exception("fail")), \
         patch("backend.agent.reflection.call_llm_b", side_effect=Exception("fail")), \
         patch("langchain_openai.ChatOpenAI", return_value=MockReflectionLLM()), \
         patch("backend.config.get_settings", return_value=_mock_settings()):
        state = make_full_report_state()
        result = await reflection_node(state)

    # Should not crash
    assert result is not None
    assert result.get("reflection_summary") is not None
    assert result["reflection_summary"]["user_preferences"] == {}
    assert result["reflection_summary"]["analysis_template"] is None


@pytest.mark.asyncio
async def test_reflection_node_a_fails_b_succeeds():
    """Verify LLM-A failure + LLM-B success: preferences empty, feedback preserved."""
    async def fail_a(llm, state, **kw):
        raise asyncio.TimeoutError("LLM-A timeout")

    async def ok_b(llm, state, **kw):
        return json.loads(MOCK_LLM_B_BASIC)

    with patch("backend.agent.reflection.call_llm_a", side_effect=fail_a), \
         patch("backend.agent.reflection.call_llm_b", side_effect=ok_b), \
         patch("langchain_openai.ChatOpenAI", return_value=MockReflectionLLM()), \
         patch("backend.config.get_settings", return_value=_mock_settings()):
        state = make_full_report_state()
        result = await reflection_node(state)

    summary = result["reflection_summary"]
    assert summary["user_preferences"] == {}
    assert summary["_llm_a_failed"] is True
    assert "skill_api_fetch" in summary["skill_feedback"]["well_performed"]


@pytest.mark.asyncio
async def test_format_reflection_card_degraded():
    """Verify degraded card shows friendly unavailability message."""
    summary = {
        "user_preferences": {},
        "analysis_template": None,
        "skill_feedback": {},
        "slot_quality_review": {
            "slots_auto_filled_correctly": [],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        },
        "_llm_a_failed": True,
        "_llm_b_failed": True,
    }
    card = format_reflection_card(summary)
    assert "暂时不可用" in card
    assert "保存" in card


@pytest.mark.asyncio
async def test_extract_json_from_markdown_fences():
    """Verify _extract_json handles markdown code fences."""
    raw = '```json\n{"user_preferences": {"output_format": "pptx"}}\n```'
    result = _extract_json(raw)
    assert result is not None
    assert result["user_preferences"]["output_format"] == "pptx"
