"""Agent E2E test cases based on mock data.

Tests the full agent pipeline: Perception → Planning → Execution → Reflection,
with all external dependencies (LLM, DB, HTTP API) mocked.

Run:  uv run pytest tests/test_agent_mock_e2e.py -v
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
import respx
import httpx

from backend.models.schemas import AnalysisPlan, TaskItem, SlotValue, StructuredIntent
from backend.skills.base import SkillInput, SkillOutput
from backend.skills.registry import SkillRegistry

# Ensure all skills are loaded before tests
import backend.skills.loader  # noqa: F401


# ════════════════════════════════════════════════════════════════
# 1. Perception Layer Tests
# ════════════════════════════════════════════════════════════════

class TestPerceptionSlotFilling:
    """Test the SlotFillingEngine with a deterministic mock LLM."""

    async def test_extract_slots_from_throughput_query(self, mock_llm):
        """Given a clear user query, slots should be extracted correctly."""
        from backend.agent.perception import SlotFillingEngine

        engine = SlotFillingEngine(llm=mock_llm, memory_store=None, max_clarification_rounds=3)
        initial_slots = engine.initialize_slots({})

        # User says: "帮我分析2026年第一季度大连港区的集装箱吞吐量"
        updated_slots = await engine.extract_slots_from_text(
            text="帮我分析2026年第一季度大连港区的集装箱吞吐量",
            current_slots=initial_slots,
            conversation_history=[],
        )

        # Verify analysis_subject was extracted
        subject = updated_slots.get("analysis_subject")
        assert subject is not None
        assert subject.value is not None
        assert "集装箱吞吐量" in str(subject.value)
        assert subject.source == "user_input"
        assert subject.confirmed is True

        # Verify time_range was extracted
        time_range = updated_slots.get("time_range")
        assert time_range is not None
        assert time_range.value is not None
        assert isinstance(time_range.value, dict)
        assert time_range.value["start"] == "2026-01-01"
        assert time_range.value["end"] == "2026-03-31"

        # Verify output_complexity was inferred
        complexity = updated_slots.get("output_complexity")
        assert complexity is not None
        assert complexity.value == "simple_table"

    async def test_empty_required_slots_detection(self, mock_llm):
        """When required slots are missing, they should be detected."""
        from backend.agent.perception import SlotFillingEngine

        engine = SlotFillingEngine(llm=mock_llm, memory_store=None)
        initial_slots = engine.initialize_slots({})

        # All required slots should be empty initially
        empty = engine.get_empty_required_slots(initial_slots, None)
        # analysis_subject (priority=2) and time_range (priority=1) must be there
        assert "time_range" in empty
        assert "analysis_subject" in empty
        # time_range has higher priority (lower number), so it should come first
        assert empty.index("time_range") < empty.index("analysis_subject")

    async def test_build_structured_intent(self, mock_llm):
        """StructuredIntent should be built correctly from filled slots."""
        from backend.agent.perception import SlotFillingEngine

        engine = SlotFillingEngine(llm=mock_llm, memory_store=None)
        slots = {
            "analysis_subject": SlotValue(value=["集装箱吞吐量"], source="user_input", confirmed=True),
            "time_range": SlotValue(
                value={"start": "2026-01-01", "end": "2026-03-31", "description": "2026年Q1"},
                source="user_input", confirmed=True,
            ),
            "output_complexity": SlotValue(value="simple_table", source="inferred", confirmed=False),
        }

        intent = engine.build_structured_intent(slots, "帮我查看集装箱吞吐量")
        assert isinstance(intent, StructuredIntent)
        assert "集装箱吞吐量" in intent.analysis_goal
        assert intent.slots["analysis_subject"].value == ["集装箱吞吐量"]

    async def test_bypass_fills_defaults(self, mock_llm):
        """When user says '按你理解执行', all empty slots should get defaults."""
        from backend.agent.perception import SlotFillingEngine

        engine = SlotFillingEngine(llm=mock_llm, memory_store=None)
        slots = engine.initialize_slots({})
        # Pre-fill analysis_subject
        slots["analysis_subject"] = SlotValue(value=["综合吞吐量"], source="user_input", confirmed=True)

        result = await engine.handle_bypass("按你理解执行", slots)
        assert result["bypass_triggered"] is True

        # time_range should now have a default
        assert slots["time_range"].value is not None
        # output_complexity should have a default
        assert slots["output_complexity"].value is not None

    async def test_max_rounds_fills_defaults(self, mock_llm):
        """After max rounds, remaining empty slots should be filled with defaults."""
        from backend.agent.perception import SlotFillingEngine

        engine = SlotFillingEngine(llm=mock_llm, memory_store=None, max_clarification_rounds=3)
        slots = engine.initialize_slots({})

        result = engine.handle_max_rounds_reached(slots)
        assert result["should_proceed_with_defaults"] is True

        # All critical slots should now have values
        assert slots["time_range"].value is not None
        assert slots["analysis_subject"].value is not None
        assert slots["output_complexity"].value is not None


# ════════════════════════════════════════════════════════════════
# 2. Execution Layer Tests — data_fetch with mocked HTTP
# ════════════════════════════════════════════════════════════════

class TestExecutionDataFetch:
    """Test the execution engine with mock API responses via respx."""

    async def test_single_data_fetch_success(self, mock_api_routes):
        """A single data_fetch task should succeed and return a DataFrame."""
        from backend.agent.execution import execute_plan

        tasks = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="获取吞吐量目标完成情况",
                skill="skill_api_fetch",
                params={
                    "endpoint_id": "getThroughputAndTargetThroughputTon",
                    "dateYear": "2026",
                    "regionName": "大连港区",
                },
            ),
        ]

        statuses, context, needs_replan = await execute_plan(tasks)

        assert statuses["T001"] == "done"
        assert "T001" in context
        output = context["T001"]
        assert output.status == "success"
        assert output.output_type == "dataframe"
        assert isinstance(output.data, pd.DataFrame)
        assert not output.data.empty
        assert "targetQty" in output.data.columns

    async def test_multiple_data_fetch_parallel(self, mock_api_routes):
        """Multiple data_fetch tasks without dependencies should run in parallel."""
        from backend.agent.execution import execute_plan

        tasks = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="获取吞吐量(吨)",
                skill="skill_api_fetch",
                params={"endpoint_id": "getThroughputAndTargetThroughputTon", "dateYear": "2026"},
            ),
            TaskItem(
                task_id="T002",
                type="data_fetch",
                name="获取泊位占用率",
                skill="skill_api_fetch",
                params={"endpoint_id": "getBerthOccupancyRateByRegion", "startDate": "2026-01-01", "endDate": "2026-03-31"},
            ),
        ]

        statuses, context, needs_replan = await execute_plan(tasks)

        assert statuses["T001"] == "done"
        assert statuses["T002"] == "done"
        assert len(context["T002"].data) == 4  # 4 regions

    async def test_invalid_endpoint_fails_gracefully(self, mock_api_routes):
        """A task with an invalid endpoint_id should fail, not crash."""
        from backend.agent.execution import execute_plan

        tasks = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="无效端点",
                skill="skill_api_fetch",
                params={"endpoint_id": "getNonExistentAPI"},
            ),
        ]

        statuses, context, _ = await execute_plan(tasks)

        assert statuses["T001"] == "failed"
        assert "未知的端点" in context["T001"].error_message

    async def test_unregistered_skill_fails_gracefully(self, mock_api_routes):
        """A task referencing a non-existent skill should fail gracefully."""
        from backend.agent.execution import execute_plan

        tasks = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="未注册技能",
                skill="skill_nonexistent",
                params={},
            ),
        ]

        statuses, context, _ = await execute_plan(tasks)

        assert statuses["T001"] == "failed"
        assert "未注册" in context["T001"].error_message


# ════════════════════════════════════════════════════════════════
# 3. Execution Layer Tests — analysis + visualization skills
# ════════════════════════════════════════════════════════════════

class TestExecutionAnalysisSkills:
    """Test analysis and visualization skills with mocked upstream data."""

    async def test_descriptive_analysis_with_upstream_data(self, mock_api_routes):
        """Descriptive analysis should compute statistics from upstream data_fetch output."""
        from backend.agent.execution import execute_plan

        tasks = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="泊位占用率数据",
                skill="skill_api_fetch",
                params={"endpoint_id": "getBerthOccupancyRateByRegion"},
            ),
            TaskItem(
                task_id="T002",
                type="analysis",
                name="泊位占用率描述性统计",
                skill="skill_desc_analysis",
                depends_on=["T001"],
                params={
                    "data_ref": "T001",
                    "target_columns": ["rate"],
                    "analysis_goal": "各港区泊位占用率分析",
                },
            ),
        ]

        # Patch ChatOpenAI import so LLM narrative fails gracefully while data_fetch still works
        with patch.dict("sys.modules", {"langchain_openai": None}):
            statuses, context, _ = await execute_plan(tasks)

        # Data fetch should succeed
        assert statuses["T001"] == "done"
        # Analysis should succeed (falls back on narrative generation)
        assert statuses["T002"] == "done"
        analysis_data = context["T002"].data
        assert isinstance(analysis_data, dict)
        assert "summary_stats" in analysis_data
        stats = analysis_data["summary_stats"]
        # Should have stats for rate
        assert "rate" in stats
        assert stats["rate"]["mean"] is not None
        assert stats["rate"]["min"] is not None
        assert stats["rate"]["max"] is not None

    async def test_bar_chart_generation(self, mock_api_routes):
        """Bar chart skill should produce ECharts option JSON from data."""
        from backend.agent.execution import execute_plan

        tasks = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="泊位占用率数据",
                skill="skill_api_fetch",
                params={"endpoint_id": "getBerthOccupancyRateByRegion"},
            ),
            TaskItem(
                task_id="T002",
                type="visualization",
                name="泊位占用率柱状图",
                skill="skill_chart_bar",
                depends_on=["T001"],
                params={
                    "data_ref": "T001",
                    "x_column": "regionName",
                    "y_columns": ["rate"],
                    "title": "各港区泊位占用率",
                },
            ),
        ]

        statuses, context, _ = await execute_plan(tasks)

        assert statuses["T001"] == "done"
        assert statuses["T002"] == "done"
        chart_data = context["T002"].data
        assert isinstance(chart_data, dict)
        # ECharts option should have xAxis, yAxis, series
        assert "xAxis" in chart_data or "series" in chart_data


# ════════════════════════════════════════════════════════════════
# 4. Execution Layer — DAG & error propagation
# ════════════════════════════════════════════════════════════════

class TestExecutionDAG:
    """Test task dependency resolution and error propagation."""

    async def test_dependency_chain(self, mock_api_routes):
        """Tasks with dependencies should execute in correct order."""
        from backend.agent.execution import execute_plan

        tasks = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="数据获取",
                skill="skill_api_fetch",
                params={"endpoint_id": "getThroughputAndTargetThroughputTon", "dateYear": "2026"},
            ),
            TaskItem(
                task_id="T002",
                type="analysis",
                name="分析",
                skill="skill_desc_analysis",
                depends_on=["T001"],
                params={"data_ref": "T001", "target_columns": ["targetQty"]},
            ),
        ]

        with patch.dict("sys.modules", {"langchain_openai": None}):
            statuses, context, _ = await execute_plan(tasks)

        assert statuses["T001"] == "done"
        assert statuses["T002"] == "done"

    async def test_cascade_failure(self, mock_api_routes):
        """When a dependency fails, dependent tasks should also fail."""
        from backend.agent.execution import execute_plan

        tasks = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="无效数据源",
                skill="skill_api_fetch",
                params={"endpoint_id": "getNonExistentAPI"},
            ),
            TaskItem(
                task_id="T002",
                type="analysis",
                name="分析",
                skill="skill_desc_analysis",
                depends_on=["T001"],
                params={"data_ref": "T001"},
            ),
        ]

        statuses, context, _ = await execute_plan(tasks)

        assert statuses["T001"] == "failed"
        assert statuses["T002"] == "failed"
        assert "依赖任务失败" in context["T002"].error_message

    async def test_data_fetch_threshold_check(self):
        """check_data_fetch_threshold should correctly apply tiered thresholds."""
        from backend.agent.execution import check_data_fetch_threshold

        # Small tier (1-3): at least 1 success
        tasks = [
            TaskItem(task_id="T001", type="data_fetch", skill="s1"),
            TaskItem(task_id="T002", type="data_fetch", skill="s2"),
        ]
        statuses = {"T001": "done", "T002": "failed"}
        result = check_data_fetch_threshold(tasks, statuses)
        assert result.passed is True
        assert result.tier == "small"

        # All failed
        statuses_all_fail = {"T001": "failed", "T002": "failed"}
        result2 = check_data_fetch_threshold(tasks, statuses_all_fail)
        assert result2.passed is False


# ════════════════════════════════════════════════════════════════
# 5. Execution Node (LangGraph integration)
# ════════════════════════════════════════════════════════════════

class TestExecutionNode:
    """Test the execution_node function that integrates with LangGraph state."""

    async def test_execution_node_with_plan(self, mock_api_routes):
        """execution_node should process a plan from state and update status."""
        from backend.agent.execution import execution_node

        plan = AnalysisPlan(
            title="2026年Q1吞吐量分析",
            analysis_goal="分析2026年Q1各港区吞吐量数据",
            tasks=[
                TaskItem(
                    task_id="T001",
                    type="data_fetch",
                    name="吞吐量数据",
                    skill="skill_api_fetch",
                    params={"endpoint_id": "getBerthOccupancyRateByRegion"},
                ),
            ],
        )

        state = {
            "session_id": "test-session",
            "user_id": "test-user",
            "messages": [],
            "analysis_plan": plan.model_dump(),
            "task_statuses": {},
            "execution_context": None,
            "needs_replan": False,
            "current_phase": "planning",
        }

        result_state = await execution_node(state)

        assert result_state["current_phase"] == "execution"
        assert result_state["task_statuses"]["T001"] == "done"
        # Mock data has 4 rows (< 10), so needs_replan is correctly True
        assert result_state["needs_replan"] is True
        # Should have an assistant message
        assert len(result_state["messages"]) > 0


# ════════════════════════════════════════════════════════════════
# 6. Full Graph Smoke Test — Perception → Planning (mocked)
# ════════════════════════════════════════════════════════════════

class TestFullGraphSmoke:
    """Smoke test the LangGraph state machine with all dependencies mocked."""

    async def test_perception_to_planning_flow(self, mock_llm, mock_api_routes):
        """Full graph should go: perception → planning → END (waiting for plan confirmation)."""
        from backend.agent.graph import build_graph, make_initial_state

        # Patch perception to use mock LLM and skip DB
        async def mock_run_perception(state):
            """Simplified perception that returns a fully-filled intent."""
            state["current_phase"] = "perception"
            slots = {
                "analysis_subject": {"value": ["集装箱吞吐量"], "source": "user_input", "confirmed": True},
                "time_range": {
                    "value": {"start": "2026-01-01", "end": "2026-03-31", "description": "2026年Q1"},
                    "source": "user_input", "confirmed": True,
                },
                "output_complexity": {"value": "simple_table", "source": "inferred", "confirmed": False},
                "domain": {"value": "D1", "source": "inferred", "confirmed": False},
                "region": {"value": "大连港区", "source": "user_input", "confirmed": True},
                "comparison_type": {"value": None, "source": "default", "confirmed": False},
                "data_granularity": {"value": None, "source": "default", "confirmed": False},
            }
            state["slots"] = slots
            state["structured_intent"] = {
                "intent_id": "test-intent-001",
                "raw_query": "帮我分析2026年第一季度集装箱吞吐量",
                "analysis_goal": "分析2026年Q1大连港区集装箱吞吐量",
                "slots": slots,
                "empty_required_slots": [],
                "clarification_history": [],
            }
            state["messages"].append({
                "role": "assistant",
                "content": "已理解您的分析需求：分析2026年Q1集装箱吞吐量",
            })
            return state

        # Patch planning to return a simple plan
        async def mock_planning_node(state):
            state["current_phase"] = "planning"
            if state.get("plan_confirmed"):
                return state
            plan = AnalysisPlan(
                title="Q1集装箱吞吐量分析",
                analysis_goal="分析2026年Q1集装箱吞吐量",
                tasks=[
                    TaskItem(
                        task_id="T001",
                        type="data_fetch",
                        name="获取集装箱吞吐量",
                        skill="skill_api_fetch",
                        params={"endpoint_id": "getThroughputAndTargetThroughputTeu", "dateYear": "2026"},
                        estimated_seconds=10,
                    ),
                ],
            )
            state["analysis_plan"] = plan.model_dump()
            state["plan_confirmed"] = False
            state["plan_version"] = 1
            state["messages"].append({
                "role": "assistant",
                "content": "## 分析方案\n\n1. 获取集装箱吞吐量数据\n\n请确认是否执行？",
            })
            return state

        with patch("backend.agent.graph.perception_node", side_effect=mock_run_perception), \
             patch("backend.agent.graph.planning_node", side_effect=mock_planning_node):

            graph = build_graph().compile()

            initial = make_initial_state(
                session_id="test-session-001",
                user_id="test-user",
                user_message="帮我分析2026年第一季度集装箱吞吐量",
            )

            events = []
            async for event in graph.astream(initial):
                events.append(event)

            # Should have at least perception and planning events
            assert len(events) >= 2

            # Last state should have a plan and be waiting for confirmation
            last_event = events[-1]
            last_state = list(last_event.values())[0]
            assert last_state.get("analysis_plan") is not None
            assert last_state.get("plan_confirmed") is False

    async def test_full_pipeline_with_plan_confirmed(self, mock_llm, mock_api_routes):
        """After plan confirmation, execution should proceed and complete."""
        from backend.agent.graph import build_graph, AgentState

        # Use a mock response with 12 rows to avoid needs_replan trigger (< 10 rows)
        large_berth_data = {
            "code": 200, "msg": "success",
            "data": [
                {"regionName": f"港区{i}", "dateMonth": f"2026-{i+1:02d}", "rate": round(0.25 + i * 0.02, 4)}
                for i in range(12)
            ],
        }
        mock_api_routes.get(
            url__regex=r".*/api/gateway/getBerthOccupancyRateByRegion.*"
        ).mock(return_value=httpx.Response(200, json=large_berth_data))

        async def mock_perception(state):
            state["current_phase"] = "perception"
            state["structured_intent"] = {
                "intent_id": "ti-002",
                "raw_query": "test",
                "analysis_goal": "泊位占用率分析",
                "slots": {
                    "domain": {"value": "D5", "source": "inferred", "confirmed": False},
                    "comparison_type": {"value": None, "source": "default", "confirmed": False},
                    "region": {"value": None, "source": "default", "confirmed": False},
                    "data_granularity": {"value": None, "source": "default", "confirmed": False},
                },
                "empty_required_slots": [],
            }
            return state

        async def mock_planning(state):
            state["current_phase"] = "planning"
            if state.get("plan_confirmed"):
                return state
            plan = AnalysisPlan(
                title="泊位占用率分析",
                tasks=[
                    TaskItem(
                        task_id="T001", type="data_fetch", name="泊位数据",
                        skill="skill_api_fetch",
                        params={"endpoint_id": "getBerthOccupancyRateByRegion"},
                    ),
                ],
            )
            state["analysis_plan"] = plan.model_dump()
            state["plan_confirmed"] = True  # Auto-confirm for test
            state["plan_version"] = 1
            return state

        with patch("backend.agent.graph.perception_node", side_effect=mock_perception), \
             patch("backend.agent.graph.planning_node", side_effect=mock_planning):

            graph = build_graph().compile()

            initial = AgentState(
                session_id="test-e2e",
                user_id="test-user",
                messages=[{"role": "user", "content": "查看泊位占用率"}],
                slots={},
                current_target_slot=None,
                empty_required_slots=[],
                structured_intent=None,
                clarification_round=0,
                analysis_plan=None,
                plan_confirmed=False,
                plan_version=0,
                task_statuses={},
                execution_context=None,
                needs_replan=False,
                reflection=None,
                current_phase="perception",
                error=None,
            )

            events = []
            async for event in graph.astream(initial):
                events.append(event)

            # Should have gone through perception → planning → execution → reflection
            assert len(events) >= 3

            # Check execution results
            execution_event = None
            for ev in events:
                if "execution" in ev:
                    execution_event = ev["execution"]
                    break

            assert execution_event is not None, "Execution node should have been reached"
            assert execution_event["task_statuses"].get("T001") == "done"


# ════════════════════════════════════════════════════════════════
# 7. Skill Registry Integrity
# ════════════════════════════════════════════════════════════════

class TestSkillRegistry:
    """Verify that all expected skills are registered and accessible."""

    def test_all_core_skills_registered(self):
        """All core skills should be registered after loader import."""
        registry = SkillRegistry.get_instance()
        expected_skills = {
            "skill_api_fetch",
            "skill_web_search",
            "skill_file_parse",
            "skill_desc_analysis",
            "skill_attribution",
            "skill_prediction",
            "skill_anomaly",
            "skill_chart_line",
            "skill_chart_bar",
            "skill_chart_waterfall",
            "skill_dashboard",
            "skill_report_pptx",
            "skill_report_docx",
            "skill_report_html",
            "skill_summary_gen",
        }
        registered = registry.skill_ids
        for skill_id in expected_skills:
            assert skill_id in registered, f"Skill {skill_id} not registered"

    def test_skill_lookup_returns_instance(self):
        """get_skill should return a BaseSkill instance."""
        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_api_fetch")
        assert skill is not None
        assert skill.skill_id == "skill_api_fetch"

    def test_skill_lookup_unknown_returns_none(self):
        """get_skill with unknown ID should return None."""
        registry = SkillRegistry.get_instance()
        assert registry.get_skill("skill_does_not_exist") is None


# ════════════════════════════════════════════════════════════════
# 8. API Registry Integrity
# ════════════════════════════════════════════════════════════════

class TestApiRegistry:
    """Verify the API registry is correctly loaded."""

    def test_endpoint_count(self):
        """Should have 122 endpoints registered (only APIs with prod data)."""
        from backend.agent.api_registry import ALL_ENDPOINTS
        assert len(ALL_ENDPOINTS) == 122

    def test_resolve_valid_endpoint(self):
        """Valid endpoint IDs should resolve correctly."""
        from backend.agent.api_registry import resolve_endpoint_id
        assert resolve_endpoint_id("getWeatherForecast") == "getWeatherForecast"
        assert resolve_endpoint_id("getThroughputAndTargetThroughputTon") == "getThroughputAndTargetThroughputTon"
        assert resolve_endpoint_id("getBerthOccupancyRateByRegion") == "getBerthOccupancyRateByRegion"

    def test_resolve_invalid_endpoint(self):
        """Invalid endpoint IDs should return None."""
        from backend.agent.api_registry import resolve_endpoint_id
        assert resolve_endpoint_id("getInvalidEndpoint") is None
        assert resolve_endpoint_id("") is None

    def test_endpoint_path_lookup(self):
        """get_endpoint_path should return correct API path."""
        from backend.agent.api_registry import get_endpoint_path
        path = get_endpoint_path("getWeatherForecast")
        assert path == "/api/gateway/getWeatherForecast"

    def test_all_domains_present(self):
        """All 7 domains (D1-D7) should have endpoints."""
        from backend.agent.api_registry import BY_DOMAIN
        for i in range(1, 8):
            domain = f"D{i}"
            assert domain in BY_DOMAIN, f"Domain {domain} missing from registry"
            assert len(BY_DOMAIN[domain]) > 0

    def test_get_endpoints_description_with_time_hint(self):
        """get_endpoints_description with time_hint should mark matching APIs with ★."""
        from backend.agent.api_registry import get_endpoints_description
        result = get_endpoints_description(
            domain_hint="D1",
            time_hint={"T_YOY"},
        )
        assert "★" in result, "Matching endpoints should be marked with ★"
        assert "D1" in result
        # Should also contain domain index header
        assert "可用数据域索引" in result

    def test_get_endpoints_description_with_granularity_hint(self):
        """get_endpoints_description with granularity_hint should mark matching APIs with ★."""
        from backend.agent.api_registry import get_endpoints_description
        result = get_endpoints_description(
            granularity_hint="G_ZONE",
        )
        assert "★" in result, "Matching endpoints should be marked with ★"
        assert "可用数据域索引" in result

    def test_get_endpoints_description_no_hints(self):
        """get_endpoints_description without hints should not have ★ markers."""
        from backend.agent.api_registry import get_endpoints_description
        result = get_endpoints_description()
        assert "★" not in result
        assert "可用数据域索引" in result

    def test_comparison_to_time_mapping(self):
        """COMPARISON_TO_TIME should map all known comparison types."""
        from backend.agent.api_registry import COMPARISON_TO_TIME
        assert "yoy" in COMPARISON_TO_TIME
        assert "mom" in COMPARISON_TO_TIME
        assert "cumulative" in COMPARISON_TO_TIME
        assert "trend" in COMPARISON_TO_TIME
        assert "snapshot" in COMPARISON_TO_TIME
        assert "historical" in COMPARISON_TO_TIME

    def test_granularity_map(self):
        """GRANULARITY_MAP should map all known granularity levels."""
        from backend.agent.api_registry import GRANULARITY_MAP
        assert "port" in GRANULARITY_MAP
        assert "zone" in GRANULARITY_MAP
        assert "company" in GRANULARITY_MAP
        assert "customer" in GRANULARITY_MAP

    def test_by_time_index(self):
        """BY_TIME index should be populated and consistent with ALL_ENDPOINTS."""
        from backend.agent.api_registry import BY_TIME, ALL_ENDPOINTS
        total = sum(len(eps) for eps in BY_TIME.values())
        assert total == len(ALL_ENDPOINTS)


# ════════════════════════════════════════════════════════════════
# 9. New Slots — non-breaking behavior
# ════════════════════════════════════════════════════════════════

class TestNewSlots:
    """Verify that new optional slots (comparison_type, region, data_granularity) don't break existing behavior."""

    def test_slot_schema_has_12_entries(self):
        """SLOT_SCHEMA should now have 12 slot definitions."""
        from backend.models.schemas import SLOT_SCHEMA
        assert len(SLOT_SCHEMA) == 12

    def test_new_slots_do_not_trigger_clarification(self, mock_llm):
        """New optional slots should never appear in empty_required_slots."""
        from backend.agent.perception import SlotFillingEngine

        engine = SlotFillingEngine(llm=mock_llm, memory_store=None)
        initial_slots = engine.initialize_slots({})
        empty = engine.get_empty_required_slots(initial_slots, None)

        # New slots are all required=False with no condition, so they should never appear
        assert "comparison_type" not in empty
        assert "region" not in empty
        assert "data_granularity" not in empty

    def test_new_slot_defaults_are_none(self, mock_llm):
        """New slots should default to None after initialization."""
        from backend.agent.perception import SlotFillingEngine

        engine = SlotFillingEngine(llm=mock_llm, memory_store=None)
        initial_slots = engine.initialize_slots({})

        for slot_name in ("comparison_type", "region", "data_granularity"):
            sv = initial_slots.get(slot_name)
            assert sv is not None, f"Slot {slot_name} should exist after initialization"
            assert sv.value is None, f"Slot {slot_name} should default to None"

    def test_domain_priority_is_7(self):
        """Domain slot should have priority 7 (not 99)."""
        from backend.models.schemas import SLOT_SCHEMA_MAP
        domain_def = SLOT_SCHEMA_MAP["domain"]
        assert domain_def.priority == 7
        assert domain_def.required is False
        assert domain_def.inferable is True
