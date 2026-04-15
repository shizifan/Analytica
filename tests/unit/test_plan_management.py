"""TC-M01~M07: 规划方案管理测试。

验证方案版本控制、修改日志、依赖清理和幂等确认。
TC-M06/M07: regenerate_plan 基于反馈重新规划。
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agent.planning import update_plan, regenerate_plan, PlanningEngine
from backend.models.schemas import AnalysisPlan, TaskItem


# ── Helpers ──────────────────────────────────────────────────

def make_test_plan(version: int = 1) -> AnalysisPlan:
    return AnalysisPlan(
        version=version,
        title="测试方案",
        analysis_goal="测试",
        tasks=[
            TaskItem(task_id="T001", type="data_fetch", name="获取数据",
                     depends_on=[], skill="skill_api_fetch",
                     params={"endpoint_id": "getThroughputSummary"}, estimated_seconds=10),
            TaskItem(task_id="T002", type="analysis", name="描述分析",
                     depends_on=["T001"], skill="skill_descriptive_analysis",
                     estimated_seconds=15),
            TaskItem(task_id="T003", type="report_gen", name="生成报告",
                     depends_on=["T002"], skill="skill_table_generation",
                     estimated_seconds=10),
        ],
        estimated_duration=35,
    )


# ═══════════════════════════════════════════════════════════════
#  TC-M01: 修改方案后版本号递增
# ═══════════════════════════════════════════════════════════════

def test_plan_version_increments_on_update():
    plan = make_test_plan(version=1)
    updated = update_plan(plan, modifications=[{"type": "remove_task", "task_id": "T003"}])
    assert updated.version == 2
    assert plan.version == 1  # 原对象不变


# ═══════════════════════════════════════════════════════════════
#  TC-M02: 修改日志被记录
# ═══════════════════════════════════════════════════════════════

def test_plan_modification_logged():
    plan = make_test_plan()
    updated = update_plan(plan, modifications=[{"type": "remove_task", "task_id": "T002"}])
    assert len(updated.revision_log) == 1
    log_entry = updated.revision_log[0]
    assert "remove_task" in str(log_entry)
    assert "T002" in str(log_entry)
    assert "changed_at" in log_entry


# ═══════════════════════════════════════════════════════════════
#  TC-M03: 删除任务时下游依赖被清理
# ═══════════════════════════════════════════════════════════════

def test_remove_task_updates_downstream_dependencies():
    plan = make_test_plan()
    # T003 depends on T002
    updated = update_plan(plan, modifications=[{"type": "remove_task", "task_id": "T002"}])
    t003 = next((t for t in updated.tasks if t.task_id == "T003"), None)
    assert t003 is not None
    assert "T002" not in t003.depends_on


# ═══════════════════════════════════════════════════════════════
#  TC-M04: 连续修改保留版本历史
# ═══════════════════════════════════════════════════════════════

def test_multiple_modifications_preserve_history():
    plan = make_test_plan(version=1)
    v2 = update_plan(plan, modifications=[{"type": "remove_task", "task_id": "T003"}])
    assert v2.version == 2
    assert len(v2.revision_log) == 1

    v3 = update_plan(v2, modifications=[{"type": "remove_task", "task_id": "T002"}])
    assert v3.version == 3
    assert len(v3.revision_log) == 2
    # First log entry is from v1->v2, second from v2->v3
    assert v3.revision_log[0]["version"] == 2
    assert v3.revision_log[1]["version"] == 3


# ═══════════════════════════════════════════════════════════════
#  TC-M05: estimated_duration 自动更新
# ═══════════════════════════════════════════════════════════════

def test_estimated_duration_updates_on_modification():
    plan = make_test_plan()
    original_duration = plan.estimated_duration
    updated = update_plan(plan, modifications=[{"type": "remove_task", "task_id": "T003"}])
    assert updated.estimated_duration < original_duration
    assert updated.estimated_duration == sum(t.estimated_seconds for t in updated.tasks)


# ═══════════════════════════════════════════════════════════════
#  regenerate_plan helpers
# ═══════════════════════════════════════════════════════════════

def _make_mock_plan_json() -> str:
    """返回 LLM 格式的规划 JSON 字符串。"""
    return json.dumps({
        "title": "重新规划方案",
        "analysis_goal": "测试重新规划",
        "tasks": [
            {
                "task_id": "T001", "type": "data_fetch", "name": "获取月度数据",
                "depends_on": [], "skill": "skill_api_fetch",
                "params": {"endpoint_id": "getThroughputSummary"},
                "estimated_seconds": 10,
            },
            {
                "task_id": "T002", "type": "report_gen", "name": "生成表格",
                "depends_on": ["T001"], "skill": "skill_table_generation",
                "estimated_seconds": 10,
            },
        ],
    }, ensure_ascii=False)


def _make_mock_llm() -> MagicMock:
    """创建返回有效规划 JSON 的模拟 LLM。"""
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = _make_mock_plan_json()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    return mock_llm


# ═══════════════════════════════════════════════════════════════
#  TC-M06: regenerate_plan 版本号递增
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_regenerate_plan_increments_version():
    mock_llm = _make_mock_llm()
    engine = PlanningEngine(llm=mock_llm, llm_timeout=30.0, max_retries=1)
    original = make_test_plan(version=2)
    intent = {"output_format": "simple_table"}
    result = await regenerate_plan(original, "改成月度数据", engine, intent)
    assert result.version == 3


# ═══════════════════════════════════════════════════════════════
#  TC-M07: regenerate_plan 修改日志包含反馈
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_regenerate_plan_logs_feedback():
    mock_llm = _make_mock_llm()
    engine = PlanningEngine(llm=mock_llm, llm_timeout=30.0, max_retries=1)
    original = make_test_plan(version=1)
    result = await regenerate_plan(original, "删除归因分析步骤", engine,
                                   {"output_format": "simple_table"})
    assert len(result.revision_log) == 1
    assert "删除归因分析步骤" in str(result.revision_log[0])
