"""Employee E2E tests -- real LLM + Mock Server.

Tests the digital employee pipeline:
- Real Qwen3-235B LLM for perception + planning
- Mock Server (mock_server_all.py) for API data
- Two-phase execution: plan generation -> plan execution

Run:
    uv run pytest tests/test_employee_e2e.py -v -m integration
    uv run pytest tests/test_employee_e2e.py -v -k "plan_generation"   # phase 1 only
    uv run pytest tests/test_employee_e2e.py -v -k "execution"         # phase 1+2
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from backend.employees.manager import EmployeeManager
from backend.employees.profile import EmployeeProfile
from backend.agent.graph import make_initial_state
from backend.models.schemas import TaskItem
from tests.artifact_recorder import record_test_artifacts

# Ensure all skills are registered
from backend.skills.loader import load_all_skills
load_all_skills()

logger = logging.getLogger("test.employee_e2e")

EMPLOYEES_DIR = Path(__file__).parent.parent / "employees"
TIMEOUT_PHASE1 = 120  # seconds for perception + planning (real LLM)
TIMEOUT_PHASE2 = 120  # seconds for execution

# ════════════════════════════════════════════════════════════════
# Mock Server — use mock_server_all.py FastAPI app via ASGI transport
#
# Instead of building mock data independently, route API gateway
# calls to the same FastAPI app used in production mock mode.
# ════════════════════════════════════════════════════════════════

from mock_server.mock_server_all import app as mock_app


# ════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════


@contextmanager
def mock_api_gateway():
    """Route API gateway calls to mock_server_all FastAPI app via ASGI transport.

    Intercepts HTTP calls made by skill_api_fetch, forwarding them to the
    FastAPI mock server in-process. LLM calls (langchain-openai) are
    unaffected since they use their own httpx instances.
    """
    from urllib.parse import urlparse
    _asgi_transport = httpx.ASGITransport(app=mock_app)
    _OriginalAsyncClient = httpx.AsyncClient  # save before patch

    class _PatchedAsyncClient(_OriginalAsyncClient):
        """AsyncClient that forwards API gateway URLs to mock_server_all."""

        async def get(self, url, **kwargs):
            if "/api/gateway/" in str(url):
                parsed = urlparse(str(url))
                async with _OriginalAsyncClient(
                    transport=_asgi_transport,
                    base_url="http://testserver",
                ) as mc:
                    return await mc.get(parsed.path, **kwargs)
            return await super().get(url, **kwargs)

        async def post(self, url, **kwargs):
            if "/api/gateway/" in str(url):
                parsed = urlparse(str(url))
                async with _OriginalAsyncClient(
                    transport=_asgi_transport,
                    base_url="http://testserver",
                ) as mc:
                    return await mc.post(parsed.path, **kwargs)
            return await super().post(url, **kwargs)

    with patch("backend.skills.data.api_fetch.httpx.AsyncClient", _PatchedAsyncClient):
        yield


@pytest.fixture(scope="module")
def mock_server():
    """Placeholder — actual API mocking done inline via mock_api_gateway()."""
    yield None


@pytest.fixture(autouse=True)
def reset_db_globals():
    """Reset cached DB engine/session factory before each test.

    This avoids 'Future attached to a different loop' errors when
    pytest-asyncio creates a new event loop per test function.
    """
    import backend.database as db_module
    db_module._engine = None
    db_module._session_factory = None
    yield
    db_module._engine = None
    db_module._session_factory = None


@pytest.fixture(scope="module")
def employee_manager():
    """Load and validate all 3 employee profiles."""
    EmployeeManager.reset()
    mgr = EmployeeManager.get_instance()
    count = mgr.load_all_profiles(EMPLOYEES_DIR)
    assert count == 3, f"Expected 3 profiles, loaded {count}"
    errors = mgr.validate_all_profiles()
    assert not errors, f"Profile validation errors: {errors}"
    yield mgr
    EmployeeManager.reset()


# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════


async def run_graph_phase1(
    manager: EmployeeManager,
    employee_id: str,
    user_message: str,
    timeout: float = TIMEOUT_PHASE1,
    max_perception_rounds: int = 3,
) -> tuple[list[dict], dict | None]:
    """Run employee graph phase 1: perception -> planning -> END.

    If perception asks for clarification (structured_intent is None),
    auto-bypass with "按你理解执行" and re-enter the graph, up to
    max_perception_rounds times.

    Returns (events, final_state).
    The graph stops at planning (plan_confirmed=False).
    """
    graph = manager.get_graph(employee_id)
    session_id = f"test-{employee_id}-{uuid4().hex[:8]}"
    current_state = make_initial_state(
        session_id, "test-user", user_message, employee_id=employee_id,
    )

    all_events: list[dict] = []
    final_state: dict | None = None

    async def _run_once(state):
        nonlocal final_state
        async for event in graph.astream(state):
            all_events.append(event)
            for _node_name, node_state in event.items():
                final_state = node_state

    for round_num in range(max_perception_rounds):
        await asyncio.wait_for(
            _run_once(current_state),
            timeout=timeout,
        )

        if final_state is None:
            break

        # If structured_intent exists, perception + planning completed
        if final_state.get("structured_intent") is not None:
            break

        # Perception asked for clarification — auto-bypass
        if round_num < max_perception_rounds - 1:
            logger.info(
                "[%s] Perception round %d asked for clarification, "
                "auto-bypassing with '按你理解执行'",
                employee_id, round_num + 1,
            )
            final_state["messages"].append({
                "role": "user",
                "content": "不需要，按你理解执行",
            })
            current_state = final_state

    return all_events, final_state


def validate_plan_scope(
    plan: dict,
    profile: EmployeeProfile,
) -> list[str]:
    """Check all plan tasks use endpoints/skills within employee scope.

    Returns a list of error messages (empty means all OK).
    """
    errors: list[str] = []
    allowed_endpoints = profile.get_endpoint_names()
    allowed_skills = profile.get_skill_ids()

    for task in plan.get("tasks", []):
        skill_id = task.get("skill", "")
        if skill_id and skill_id not in allowed_skills:
            errors.append(
                f"Task {task.get('task_id')}: skill '{skill_id}' "
                f"not in allowed_skills {sorted(allowed_skills)}"
            )

        endpoint_id = task.get("params", {}).get("endpoint_id")
        if endpoint_id and endpoint_id not in allowed_endpoints:
            errors.append(
                f"Task {task.get('task_id')}: endpoint '{endpoint_id}' "
                f"not in allowed_endpoints ({len(allowed_endpoints)} endpoints)"
            )

    return errors


# ════════════════════════════════════════════════════════════════
# Test Scenarios (3 employees x 3-4 query types = 10)
# ════════════════════════════════════════════════════════════════

SCENARIOS = [
    # throughput_analyst
    ("throughput_analyst", "simple_table", "2026年大连港区吞吐量目标完成情况"),
    ("throughput_analyst", "chart_text", "各港区泊位占用率趋势，生成折线图"),
    ("throughput_analyst", "full_report", "生成2026年3月生产运营月度报告"),
    # customer_insight
    ("customer_insight", "simple_table", "当月战略客户贡献排名Top10"),
    ("customer_insight", "chart_text", "战略客户当期月度趋势分析，生成折线图"),
    ("customer_insight", "full_report", "生成战略客户季度洞察报告PPT"),
    # asset_investment
    ("asset_investment", "simple_table", "各港区资产数量和价值分布"),
    ("asset_investment", "chart_text", "近5年投资计划与完成情况历年趋势，生成折线图"),
    ("asset_investment", "full_report", "生成2026年资产投资综合报告"),
    # asset_investment D7 equipment
    ("asset_investment", "equip_trend", "生产设备利用率和完好率月度趋势分析"),
]


# ════════════════════════════════════════════════════════════════
# 1. Plan Generation Tests (Phase 1: real LLM)
# ════════════════════════════════════════════════════════════════


@pytest.mark.integration
@pytest.mark.llm_real
class TestEmployeePlanGeneration:
    """Phase 1 E2E: perception -> planning with real LLM.

    Validates:
    - structured_intent is produced by perception
    - analysis_plan has tasks
    - All endpoints/skills are within employee scope
    - plan_confirmed == False (Human-in-the-Loop pause)
    """

    @pytest.mark.parametrize(
        "employee_id,query_type,user_message",
        SCENARIOS,
        ids=[f"{e}_{q}" for e, q, _ in SCENARIOS],
    )
    async def test_plan_within_scope(
        self, employee_manager, employee_id, query_type, user_message,
    ):
        events, state = await run_graph_phase1(
            employee_manager, employee_id, user_message,
        )

        # Basic sanity
        assert state is not None, "Graph produced no output"
        assert state.get("error") is None, f"Graph error: {state.get('error')}"

        # Perception should produce structured_intent
        intent = state.get("structured_intent")
        assert intent is not None, (
            f"Perception failed to produce structured_intent for: '{user_message}'"
        )

        # Planning should produce analysis_plan
        plan = state.get("analysis_plan")
        assert plan is not None, (
            f"Planning failed to produce analysis_plan for: '{user_message}'"
        )

        tasks = plan.get("tasks", [])
        assert len(tasks) > 0, "Plan should have at least one task"

        # Validate all endpoints/skills are within employee scope
        profile = employee_manager.get_employee(employee_id)
        scope_errors = validate_plan_scope(plan, profile)
        assert not scope_errors, (
            f"Plan violates employee scope:\n" + "\n".join(scope_errors)
        )

        # Human-in-the-Loop: plan should await confirmation
        assert state.get("plan_confirmed") is False, (
            "Plan should await confirmation (plan_confirmed=False)"
        )

        logger.info(
            "[%s/%s] Plan: %d tasks -- %s",
            employee_id, query_type, len(tasks), plan.get("title", ""),
        )


# ════════════════════════════════════════════════════════════════
# 2. Full E2E Tests (Phase 1 + Phase 2: real LLM + mock server)
# ════════════════════════════════════════════════════════════════


@pytest.mark.integration
@pytest.mark.llm_real
class TestEmployeeFullE2E:
    """Full E2E: plan generation (real LLM) + execution (mock server).

    Validates:
    - Plan is generated with correct scope (phase 1)
    - All tasks complete successfully with no failures (phase 2)
    """

    @pytest.mark.parametrize(
        "employee_id,query_type,user_message",
        SCENARIOS,
        ids=[f"{e}_{q}" for e, q, _ in SCENARIOS],
    )
    async def test_full_pipeline(
        self,
        employee_manager,
        employee_id,
        query_type,
        user_message,
    ):
        # ── Phase 1: perception + planning (real LLM, no mocking) ──
        events, state = await run_graph_phase1(
            employee_manager, employee_id, user_message,
        )
        assert state is not None, "Graph produced no output"
        assert state.get("error") is None, f"Phase 1 error: {state.get('error')}"

        plan = state.get("analysis_plan")
        assert plan is not None, f"Phase 1 failed to produce plan for: '{user_message}'"

        raw_tasks = plan.get("tasks", [])
        assert len(raw_tasks) > 0, "Plan has no tasks"

        # Validate scope
        profile = employee_manager.get_employee(employee_id)
        scope_errors = validate_plan_scope(plan, profile)
        assert not scope_errors, (
            f"Plan violates scope:\n" + "\n".join(scope_errors)
        )

        # ── Phase 2: execution (mock API gateway, real LLM for analysis) ──
        from backend.agent.execution import execute_plan

        allowed_skills = profile.get_skill_ids()
        tasks = [
            TaskItem(**t) if isinstance(t, dict) else t
            for t in raw_tasks
        ]

        # mock_api_gateway() only intercepts httpx in the api_fetch module,
        # leaving LLM httpx calls (langchain-openai) untouched
        with mock_api_gateway():
            statuses, context, needs_replan = await asyncio.wait_for(
                execute_plan(tasks, allowed_skills=allowed_skills),
                timeout=TIMEOUT_PHASE2,
            )

        # Record artifacts to disk (never affects test outcome)
        try:
            record_test_artifacts(
                employee_id=employee_id,
                query_type=query_type,
                user_message=user_message,
                state=state,
                task_statuses=statuses,
                execution_context=context,
                needs_replan=needs_replan,
            )
        except Exception as rec_err:
            logger.warning("Artifact recording failed: %s", rec_err)

        # All tasks should succeed
        success_count = sum(1 for v in statuses.values() if v == "done")
        fail_count = sum(1 for v in statuses.values() if v == "failed")
        total = len(statuses)

        # Collect failure details for assertion message
        failures = [
            f"  {tid}: {ctx.error_message}"
            for tid, ctx in context.items()
            if ctx.status == "failed"
        ]

        assert fail_count == 0, (
            f"Tasks failed: {fail_count}/{total}\n"
            f"Failures:\n" + "\n".join(failures)
        )

        logger.info(
            "[%s/%s] Full E2E: %d/%d tasks done",
            employee_id, query_type, success_count, total,
        )


# ════════════════════════════════════════════════════════════════
# 3. Skill Whitelist Enforcement (unit-level, no LLM needed)
# ════════════════════════════════════════════════════════════════


class TestEmployeeSkillWhitelist:
    """Verify that execution blocks skills outside the employee's whitelist."""

    async def test_blocked_skill_rejected(self, employee_manager):
        """customer_insight does not have skill_prediction -- it should be blocked."""
        from backend.agent.execution import execute_plan

        profile = employee_manager.get_employee("customer_insight")
        allowed_skills = profile.get_skill_ids()
        assert "skill_prediction" not in allowed_skills

        tasks = [
            TaskItem(
                task_id="T_BLOCKED",
                type="analysis",
                name="prediction (should be blocked)",
                skill="skill_prediction",
                params={},
            ),
        ]

        statuses, context, _ = await execute_plan(
            tasks, allowed_skills=allowed_skills,
        )

        assert statuses["T_BLOCKED"] == "failed"
        assert "不在当前员工范围内" in context["T_BLOCKED"].error_message

    async def test_allowed_skill_not_blocked(self, employee_manager):
        """skill_api_fetch is in all employees -- it should pass the whitelist check.

        The task may fail due to invalid endpoint, but the error should NOT be
        about the whitelist.
        """
        from backend.agent.execution import _execute_single_task

        profile = employee_manager.get_employee("throughput_analyst")
        allowed_skills = profile.get_skill_ids()
        assert "skill_api_fetch" in allowed_skills

        task = TaskItem(
            task_id="T_ALLOWED",
            type="data_fetch",
            name="whitelist pass-through test",
            skill="skill_api_fetch",
            params={"endpoint_id": "INVALID_ENDPOINT_FOR_TESTING"},
        )

        _, output = await _execute_single_task(
            task, {}, allowed_skills=allowed_skills,
        )
        # Should NOT fail because of whitelist
        assert "不在当前员工范围内" not in (output.error_message or "")

    async def test_no_whitelist_allows_all(self, employee_manager):
        """When allowed_skills is None, no whitelist check should occur."""
        from backend.agent.execution import _execute_single_task

        task = TaskItem(
            task_id="T_NO_WL",
            type="data_fetch",
            name="no whitelist test",
            skill="skill_api_fetch",
            params={"endpoint_id": "INVALID_ENDPOINT_FOR_TESTING"},
        )

        _, output = await _execute_single_task(task, {}, allowed_skills=None)
        # Should NOT fail because of whitelist (fail for other reason)
        assert "不在当前员工范围内" not in (output.error_message or "")


# ════════════════════════════════════════════════════════════════
# 4. Profile Loading & Validation
# ════════════════════════════════════════════════════════════════


class TestEmployeeProfileLoading:
    """Verify employee profiles load correctly and pass validation."""

    def test_three_profiles_loaded(self, employee_manager):
        """All 3 YAML profiles should be loaded."""
        employees = employee_manager.list_employees()
        assert len(employees) == 3
        ids = {e.employee_id for e in employees}
        assert ids == {"throughput_analyst", "customer_insight", "asset_investment"}

    def test_throughput_analyst_domains(self, employee_manager):
        """throughput_analyst should be bound to D1+D2."""
        profile = employee_manager.get_employee("throughput_analyst")
        assert profile is not None
        assert profile.domains == ["D1", "D2"]
        assert "skill_api_fetch" in profile.get_skill_ids()
        assert "skill_prediction" in profile.get_skill_ids()
        assert len(profile.get_endpoint_names()) > 0

    def test_customer_insight_domains(self, employee_manager):
        """customer_insight should be bound to D2+D3."""
        profile = employee_manager.get_employee("customer_insight")
        assert profile is not None
        assert profile.domains == ["D2", "D3"]
        # Should NOT have prediction skill
        assert "skill_prediction" not in profile.get_skill_ids()

    def test_asset_investment_domains(self, employee_manager):
        """asset_investment should be bound to D5+D6+D7."""
        profile = employee_manager.get_employee("asset_investment")
        assert profile is not None
        assert profile.domains == ["D5", "D6", "D7"]

    def test_extra_slots_defined(self, employee_manager):
        """Each employee should have extra_slots defined."""
        for emp in employee_manager.list_employees():
            extra_names = emp.get_extra_slot_names()
            assert len(extra_names) >= 2, (
                f"{emp.employee_id} should have at least 2 extra_slots"
            )

    def test_slot_constraints_valid(self, employee_manager):
        """Slot constraints should reference known domains."""
        for emp in employee_manager.list_employees():
            sc = emp.perception.slot_constraints
            if "domain" in sc:
                for v in sc["domain"].allowed_values:
                    assert v in emp.domains, (
                        f"{emp.employee_id}: domain constraint '{v}' "
                        f"not in domains {emp.domains}"
                    )

    def test_endpoints_within_domains(self, employee_manager):
        """All resolved endpoints should belong to the employee's domains."""
        from backend.agent.api_registry import BY_NAME

        for emp in employee_manager.list_employees():
            endpoints = emp.get_endpoint_names()
            for ep_name in endpoints:
                ep = BY_NAME.get(ep_name)
                assert ep is not None, f"Endpoint {ep_name} not in BY_NAME"
                assert ep.domain in emp.domains, (
                    f"{emp.employee_id}: endpoint {ep_name} domain={ep.domain} "
                    f"not in {emp.domains}"
                )

    def test_skills_all_registered(self, employee_manager):
        """All skills referenced in profiles should be registered."""
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry.get_instance()
        for emp in employee_manager.list_employees():
            for sid in emp.skills:
                assert sid in registry.skill_ids, (
                    f"{emp.employee_id}: skill {sid} not registered"
                )
