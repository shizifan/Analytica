"""TC-PLAN-RETRY + TC-PLAN-ADV: 规划层 LLM 重试和对抗性输入测试。

验证超时重试、JSON截断重试、超量任务截断、循环依赖修复。
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agent.planning import PlanningEngine, _has_cycle
from backend.exceptions import PlanningError


# ── Helpers ──────────────────────────────────────────────────

def make_valid_simple_plan() -> dict:
    return {
        "title": "简单查询",
        "analysis_goal": "测试",
        "estimated_duration": 20,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch", "name": "获取数据",
             "depends_on": [], "skill": "skill_api_fetch",
             "params": {"endpoint_id": "getThroughputSummary"}, "estimated_seconds": 10},
            {"task_id": "T002", "type": "report_gen", "name": "生成表格",
             "depends_on": ["T001"], "skill": "skill_table_generation",
             "params": {}, "estimated_seconds": 10},
        ],
    }


MOCK_SKILLS = {"skill_api_fetch": {}, "skill_table_generation": {}, "skill_descriptive_analysis": {}}
MOCK_ENDPOINTS = {"getThroughputSummary": {}}


def make_engine_with_callable(side_effect) -> PlanningEngine:
    """Create engine with a callable mock LLM."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(side_effect=side_effect)
    return PlanningEngine(llm=mock_llm, llm_timeout=5.0, max_retries=2)


# ═══════════════════════════════════════════════════════════════
#  TC-PLAN-RETRY01: 首次超时后重试成功
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_planning_retries_on_timeout():
    call_count = 0

    async def timeout_then_success(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError("Planning LLM timeout")
        return MagicMock(content=json.dumps(make_valid_simple_plan()))

    engine = make_engine_with_callable(timeout_then_success)
    intent = {"output_complexity": "simple_table"}
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert call_count == 2
    assert plan is not None
    assert len(plan.tasks) >= 1


# ═══════════════════════════════════════════════════════════════
#  TC-PLAN-RETRY02: 连续失败后抛出 PlanningError
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_planning_raises_after_max_retries():
    async def always_fail(*args, **kwargs):
        raise asyncio.TimeoutError()

    engine = make_engine_with_callable(always_fail)
    intent = {"output_complexity": "simple_table"}
    with pytest.raises(PlanningError, match="规划失败"):
        await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)


# ═══════════════════════════════════════════════════════════════
#  TC-PLAN-RETRY04: JSON 截断后重试
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_planning_truncated_json_retries():
    call_count = 0

    async def truncated_then_complete(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(content='{"title": "测试", "tasks": [{"task_id": "T1"')
        return MagicMock(content=json.dumps(make_valid_simple_plan()))

    engine = make_engine_with_callable(truncated_then_complete)
    intent = {"output_complexity": "simple_table"}
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert call_count == 2
    assert plan is not None


# ═══════════════════════════════════════════════════════════════
#  TC-PLAN-ADV01: 超量任务被截断至上限
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_planning_caps_task_count_at_maximum():
    bloated_plan = {
        "title": "超量方案",
        "analysis_goal": "测试",
        "estimated_duration": 150,
        "tasks": [
            {"task_id": f"T{i:03d}", "type": "data_fetch", "skill": "skill_api_fetch",
             "depends_on": [], "params": {"endpoint_id": "getThroughputSummary"},
             "name": f"任务{i}", "estimated_seconds": 5}
            for i in range(1, 16)
        ],
    }
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=json.dumps(bloated_plan)))
    engine = PlanningEngine(llm=mock_llm, llm_timeout=30.0, max_retries=1)
    intent = {"output_complexity": "full_report"}
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert len(plan.tasks) <= 8, "超量任务应被截断至最大值 8"


# ═══════════════════════════════════════════════════════════════
#  TC-PLAN-ADV02: 循环依赖被检测并修复
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_planning_detects_and_fixes_circular_dependency():
    circular_plan = {
        "title": "循环方案",
        "analysis_goal": "测试",
        "estimated_duration": 30,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch", "skill": "skill_api_fetch",
             "depends_on": ["T002"], "params": {"endpoint_id": "getThroughputSummary"},
             "name": "T1", "estimated_seconds": 5},
            {"task_id": "T002", "type": "analysis", "skill": "skill_descriptive_analysis",
             "depends_on": ["T001"], "params": {},
             "name": "T2", "estimated_seconds": 10},
        ],
    }
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=json.dumps(circular_plan)))
    engine = PlanningEngine(llm=mock_llm, llm_timeout=30.0, max_retries=1)
    intent = {"output_complexity": "simple_table"}
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    graph = {t.task_id: t.depends_on for t in plan.tasks}
    assert not _has_cycle(graph), "修复后的规划不应含循环依赖"


# ═══════════════════════════════════════════════════════════════
#  TC-PLAN-ADV03: 多个 <think> 块混合内容
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_planning_handles_mixed_think_and_json():
    mixed_output = (
        "<think>首先我需要理解用户意图...</think>\n"
        "好的，我来制定分析方案：\n"
        "<think>需要选择合适的端点...</think>\n"
        + json.dumps(make_valid_simple_plan())
    )
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=mixed_output))
    engine = PlanningEngine(llm=mock_llm, llm_timeout=30.0, max_retries=1)
    intent = {"output_complexity": "simple_table"}
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert plan is not None
    assert len(plan.tasks) >= 1
