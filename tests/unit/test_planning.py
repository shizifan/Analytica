"""TC-P01~P11: 规划节点基础测试。

基于 Mock LLM 输出验证规划引擎的核心功能：
任务数量控制、依赖图校验、幻觉过滤、<think>标签处理、JSON容错。
"""
import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.agent.planning import (
    PlanningEngine,
    format_plan_as_markdown,
    parse_planning_llm_output,
    update_plan,
    _has_cycle,
)
from backend.exceptions import PlanningError
from backend.models.schemas import AnalysisPlan, TaskItem


# ── Test Helpers ─────────────────────────────────────────────

MOCK_SKILLS = {
    "skill_api_fetch": {},
    "skill_descriptive_analysis": {},
    "skill_trend_analysis": {},
    "skill_attribution_analysis": {},
    "skill_narrative_generation": {},
    "skill_echarts_generation": {},
    "skill_table_generation": {},
    "skill_pptx_generation": {},
    "skill_html_generation": {},
    "skill_report_html": {},
}

MOCK_ENDPOINTS = {
    "getThroughputSummary": {},
    "getThroughputByBusinessType": {},
    "getThroughputTrendByMonth": {},
    "getContainerThroughput": {},
    "getBerthOccupancyRate": {},
    "getMarketMonthlyThroughput": {},
    "getMarketTrendChart": {},
    "getMarketZoneThroughput": {},
    "getKeyEnterpriseContribution": {},
    "getCustomerContributionRanking": {},
    "getStrategicCustomerThroughput": {},
    "getAssetOverview": {},
    "getInvestPlanSummary": {},
    "getInvestPlanProgress": {},
    "getCapitalProjectList": {},
}


def make_structured_intent(
    complexity: str = "simple_table",
    domain: str | None = None,
    subject: list[str] | None = None,
    **kwargs,
) -> dict:
    intent = {
        "output_complexity": complexity,
        "analysis_goal": "测试分析目标",
        "slots": {
            "output_complexity": {"value": complexity, "source": "user_input", "confirmed": True},
            "analysis_subject": {"value": subject or ["测试指标"], "source": "user_input", "confirmed": True},
            "time_range": {"value": {"start": "2026-01-01", "end": "2026-03-31", "description": "2026Q1"}, "source": "user_input", "confirmed": True},
        },
    }
    if domain:
        intent["domain"] = domain
        intent["slots"]["domain"] = {"value": domain, "source": "inferred", "confirmed": False}
    intent.update(kwargs)
    return intent


def make_plan_json(task_count: int = 3, **overrides) -> str:
    tasks = []
    for i in range(1, task_count + 1):
        tasks.append({
            "task_id": f"T{i:03d}",
            "type": "data_fetch" if i <= task_count // 2 + 1 else "analysis",
            "name": f"任务{i}",
            "description": f"测试任务{i}的描述",
            "depends_on": [f"T{i-1:03d}"] if i > 1 else [],
            "skill": "skill_api_fetch" if i <= task_count // 2 + 1 else "skill_descriptive_analysis",
            "params": {"endpoint_id": "getThroughputSummary"} if i <= task_count // 2 + 1 else {},
            "estimated_seconds": 10,
        })
    plan = {
        "title": "测试方案",
        "analysis_goal": "测试分析目标",
        "estimated_duration": task_count * 10,
        "tasks": tasks,
        "report_structure": None,
    }
    plan.update(overrides)
    return json.dumps(plan, ensure_ascii=False)


def make_full_report_plan_json(task_count: int = 6) -> str:
    tasks = []
    for i in range(1, task_count + 1):
        task_type = "data_fetch" if i <= 3 else ("analysis" if i <= 5 else "report_gen")
        tasks.append({
            "task_id": f"T{i:03d}",
            "type": task_type,
            "name": f"任务{i}",
            "description": f"测试任务{i}",
            "depends_on": [f"T{i-1:03d}"] if i > 1 else [],
            "skill": "skill_api_fetch" if task_type == "data_fetch" else "skill_descriptive_analysis",
            "params": {"endpoint_id": "getThroughputSummary"} if task_type == "data_fetch" else {},
            "estimated_seconds": 15,
        })
    return json.dumps({
        "title": "全报告方案",
        "analysis_goal": "港口运营报告",
        "estimated_duration": task_count * 15,
        "tasks": tasks,
        "report_structure": {"sections": ["封面", "目录", "趋势分析", "归因分析", "结论"]},
    }, ensure_ascii=False)


def make_test_plan(task_count: int = 3, version: int = 1, complexity: str = "simple_table") -> AnalysisPlan:
    tasks = []
    for i in range(1, task_count + 1):
        tasks.append(TaskItem(
            task_id=f"T{i:03d}",
            type="data_fetch" if i == 1 else "analysis",
            name=f"任务{i}",
            depends_on=[f"T{i-1:03d}"] if i > 1 else [],
            skill="skill_api_fetch" if i == 1 else "skill_descriptive_analysis",
            params={"endpoint_id": "getThroughputSummary"} if i == 1 else {},
            estimated_seconds=10,
        ))
    return AnalysisPlan(
        version=version,
        title="测试方案",
        analysis_goal="测试目标",
        estimated_duration=task_count * 10,
        tasks=tasks,
        report_structure={"sections": ["封面", "内容"]} if complexity == "full_report" else None,
    )


def make_test_plan_with_deps() -> AnalysisPlan:
    """T001 -> T002 -> T003 chain."""
    return AnalysisPlan(
        version=1,
        title="带依赖的方案",
        tasks=[
            TaskItem(task_id="T001", type="data_fetch", name="获取数据", depends_on=[], skill="skill_api_fetch", params={"endpoint_id": "getThroughputSummary"}),
            TaskItem(task_id="T002", type="analysis", name="分析", depends_on=["T001"], skill="skill_descriptive_analysis"),
            TaskItem(task_id="T003", type="report_gen", name="生成报告", depends_on=["T002"], skill="skill_table_generation"),
        ],
    )


def make_mock_engine(return_value: str) -> PlanningEngine:
    """Create a PlanningEngine with a mock LLM that returns the given string."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=return_value))
    return PlanningEngine(llm=mock_llm, llm_timeout=30.0, max_retries=2)


# ═══════════════════════════════════════════════════════════════
#  TC-P01: simple_table 场景生成 2-3 个任务
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_simple_table_generates_2_to_3_tasks():
    engine = make_mock_engine(make_plan_json(task_count=2))
    intent = make_structured_intent("simple_table")
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert 2 <= len(plan.tasks) <= 3


# ═══════════════════════════════════════════════════════════════
#  TC-P02: full_report 场景生成 5-8 个任务
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_full_report_generates_5_to_8_tasks():
    engine = make_mock_engine(make_full_report_plan_json(task_count=6))
    intent = make_structured_intent("full_report")
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert 5 <= len(plan.tasks) <= 8


# ═══════════════════════════════════════════════════════════════
#  TC-P03: 任务依赖关系无环
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_task_dependencies_are_acyclic():
    engine = make_mock_engine(make_full_report_plan_json(task_count=6))
    intent = make_structured_intent("full_report")
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    graph = {t.task_id: t.depends_on for t in plan.tasks}
    assert not _has_cycle(graph), "任务依赖图中存在环"


# ═══════════════════════════════════════════════════════════════
#  TC-P04: 任务依赖引用的 task_id 必须存在
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_task_dependency_references_exist():
    engine = make_mock_engine(make_full_report_plan_json(task_count=5))
    intent = make_structured_intent("full_report")
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    all_task_ids = {t.task_id for t in plan.tasks}
    for task in plan.tasks:
        for dep in task.depends_on:
            assert dep in all_task_ids, f"任务 {task.task_id} 依赖不存在的 {dep}"


# ═══════════════════════════════════════════════════════════════
#  TC-P05: 幻觉技能被过滤
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_hallucinated_skill_filtered_out():
    plan_with_fake = {
        "title": "测试",
        "analysis_goal": "测试",
        "estimated_duration": 30,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch", "name": "真实任务", "depends_on": [],
             "skill": "skill_api_fetch", "params": {}, "estimated_seconds": 10},
            {"task_id": "T002", "type": "analysis", "name": "港口排名", "depends_on": [],
             "skill": "skill_port_national_ranking", "params": {}, "estimated_seconds": 10},
            {"task_id": "T003", "type": "analysis", "name": "收入预测", "depends_on": [],
             "skill": "skill_revenue_forecast_external", "params": {}, "estimated_seconds": 10},
        ],
    }
    engine = make_mock_engine(json.dumps(plan_with_fake))
    intent = make_structured_intent("simple_table")
    plan = await engine.generate_plan(intent, available_skills={"skill_api_fetch": {}}, available_endpoints=MOCK_ENDPOINTS)
    task_ids = {t.task_id for t in plan.tasks}
    assert "T001" in task_ids
    assert "T002" not in task_ids, "幻觉技能 skill_port_national_ranking 应被过滤"
    assert "T003" not in task_ids, "幻觉技能 skill_revenue_forecast_external 应被过滤"


# ═══════════════════════════════════════════════════════════════
#  TC-P06: 幻觉端点被过滤
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_hallucinated_endpoint_filtered_out():
    plan_with_fake = {
        "title": "测试",
        "analysis_goal": "测试",
        "estimated_duration": 30,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch", "name": "获取吞吐量", "depends_on": [],
             "skill": "skill_api_fetch", "params": {"endpoint_id": "getThroughputSummary"}, "estimated_seconds": 10},
            {"task_id": "T002", "type": "data_fetch", "name": "全国排名", "depends_on": [],
             "skill": "skill_api_fetch", "params": {"endpoint_id": "getPortNationalRanking"}, "estimated_seconds": 10},
            {"task_id": "T003", "type": "data_fetch", "name": "收入", "depends_on": [],
             "skill": "skill_api_fetch", "params": {"endpoint_id": "getRevenueByBusinessType"}, "estimated_seconds": 10},
        ],
    }
    engine = make_mock_engine(json.dumps(plan_with_fake))
    intent = make_structured_intent("simple_table")
    plan = await engine.generate_plan(
        intent,
        available_skills=MOCK_SKILLS,
        available_endpoints={"getThroughputSummary": {}},
    )
    endpoint_ids = {t.params.get("endpoint_id") for t in plan.tasks}
    assert "getThroughputSummary" in endpoint_ids
    assert "getPortNationalRanking" not in endpoint_ids
    assert "getRevenueByBusinessType" not in endpoint_ids


# ═══════════════════════════════════════════════════════════════
#  TC-P07: LLM 输出含 <think> 标签被正确剥离
# ═══════════════════════════════════════════════════════════════

def test_planning_strips_think_tags():
    raw = "<think>规划思考过程...</think>\n" + json.dumps({
        "title": "测试",
        "estimated_duration": 30,
        "tasks": [{"task_id": "T001", "type": "data_fetch", "name": "获取数据",
                   "depends_on": [], "skill": "skill_api_fetch", "params": {}, "estimated_seconds": 10}],
    })
    parsed = parse_planning_llm_output(raw)
    assert parsed["title"] == "测试"
    assert len(parsed["tasks"]) == 1


# ═══════════════════════════════════════════════════════════════
#  TC-P08: LLM 输出非法 JSON 的容错
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_planning_invalid_json_raises_planning_error():
    engine = make_mock_engine("这不是JSON，我在思考但忘记输出JSON了")
    intent = make_structured_intent("simple_table")
    with pytest.raises(PlanningError, match="JSON"):
        await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)


# ═══════════════════════════════════════════════════════════════
#  TC-P09: 规划 Prompt 中包含约束提示
# ═══════════════════════════════════════════════════════════════

def test_planning_prompt_includes_endpoint_caveats():
    engine = PlanningEngine()
    intent = make_structured_intent("chart_text", subject=["货类结构"])
    prompt = engine._build_prompt(intent, "chart_text")
    assert "businessSegment" in prompt or "必填" in prompt


# ═══════════════════════════════════════════════════════════════
#  TC-P10: full_report 包含 report_structure
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_full_report_plan_has_report_structure():
    engine = make_mock_engine(make_full_report_plan_json(task_count=6))
    intent = make_structured_intent("full_report")
    plan = await engine.generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert plan.report_structure is not None
    assert "sections" in plan.report_structure


# ═══════════════════════════════════════════════════════════════
#  TC-P11: Markdown 展示格式验证
# ═══════════════════════════════════════════════════════════════

def test_plan_markdown_format():
    plan = make_test_plan(task_count=3, complexity="chart_text")
    md = format_plan_as_markdown(plan)
    assert "T001" in md
    assert "T002" in md
    assert "T003" in md
    assert "预计" in md
    assert "确认" in md
