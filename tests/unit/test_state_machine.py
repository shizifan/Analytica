"""TC-SM01~SM10: LangGraph 状态机测试。

验证路由函数、MySQLCheckpointSaver 的序列化/反序列化和会话隔离。
SM08/09/10: route_after_execution 三路分支覆盖。
"""
import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from backend.agent.graph import (
    AgentState,
    route_after_perception,
    route_after_planning,
    route_after_execution,
    MySQLCheckpointSaver,
)

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "mysql+aiomysql://root@localhost:3306/analytica"
)


# ── State Helpers ────────────────────────────────────────────

def make_state_with_intent() -> AgentState:
    return AgentState(
        session_id="test",
        user_id="test",
        messages=[],
        slots={},
        structured_intent={"analysis_goal": "测试"},
        empty_required_slots=[],
        clarification_round=0,
        plan_confirmed=False,
        current_phase="perception",
    )


def make_state_with_empty_slots(empty: list[str]) -> AgentState:
    return AgentState(
        session_id="test",
        user_id="test",
        messages=[],
        slots={},
        structured_intent=None,
        empty_required_slots=empty,
        clarification_round=0,
        plan_confirmed=False,
        current_phase="perception",
    )


def make_state_with_plan(confirmed: bool = False) -> AgentState:
    return AgentState(
        session_id="test",
        user_id="test",
        messages=[],
        slots={},
        structured_intent={"analysis_goal": "测试"},
        analysis_plan={"title": "测试方案", "tasks": []},
        plan_confirmed=confirmed,
        plan_version=1,
        current_phase="planning",
    )


def make_test_agent_state(session_id: str = "test", plan_version: int = 1) -> dict:
    return {
        "session_id": session_id,
        "user_id": "test_user",
        "messages": [{"role": "user", "content": "测试"}],
        "slots": {},
        "structured_intent": {"analysis_goal": "测试"},
        "plan_version": plan_version,
        "plan_confirmed": False,
        "current_phase": "planning",
    }


# ── DB Fixtures ──────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


# ═══════════════════════════════════════════════════════════════
#  TC-SM01: 感知到规划的状态转移
# ═══════════════════════════════════════════════════════════════

def test_route_perception_to_planning_when_intent_set():
    state = make_state_with_intent()
    next_node = route_after_perception(state)
    assert next_node == "planning"


# ═══════════════════════════════════════════════════════════════
#  TC-SM02: 感知节点有空槽时回到 END（等待用户回复）
# ═══════════════════════════════════════════════════════════════

def test_route_perception_to_end_when_empty_slots():
    state = make_state_with_empty_slots(["time_range"])
    # structured_intent is None → route to END
    next_node = route_after_perception(state)
    assert next_node == "__end__"


# ═══════════════════════════════════════════════════════════════
#  TC-SM03: 规划未确认时暂停
# ═══════════════════════════════════════════════════════════════

def test_route_planning_to_end_when_not_confirmed():
    state = make_state_with_plan(confirmed=False)
    next_node = route_after_planning(state)
    assert next_node == "__end__"


# ═══════════════════════════════════════════════════════════════
#  TC-SM04: 规划确认后进入执行
# ═══════════════════════════════════════════════════════════════

def test_route_planning_to_execution_when_confirmed():
    state = make_state_with_plan(confirmed=True)
    next_node = route_after_planning(state)
    assert next_node == "execution"


# ═══════════════════════════════════════════════════════════════
#  TC-SM05: MySQLCheckpointSaver 写入和读取
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_mysql_checkpoint_put_and_get(test_db_session):
    saver = MySQLCheckpointSaver(session=test_db_session)
    session_id = str(uuid4())
    original_state = make_test_agent_state(session_id=session_id, plan_version=1)
    config = {"configurable": {"thread_id": session_id}}

    await saver.put(config, original_state, {}, {})
    loaded = await saver.get(config)

    assert loaded is not None
    assert loaded["session_id"] == session_id
    assert loaded["plan_version"] == 1


# ═══════════════════════════════════════════════════════════════
#  TC-SM06: Checkpoint 持久化后可恢复
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_checkpoint_persistence_and_recovery(test_db_session):
    saver = MySQLCheckpointSaver(session=test_db_session)
    session_id = str(uuid4())
    state = make_test_agent_state(session_id=session_id, plan_version=2)
    state["plan_confirmed"] = False
    state["structured_intent"] = {"analysis_goal": "集装箱分析"}

    config = {"configurable": {"thread_id": session_id}}
    await saver.put(config, state, {}, {})

    # Recover
    loaded = await saver.get(config)
    assert loaded is not None
    assert loaded["structured_intent"] is not None
    assert loaded["plan_confirmed"] is False
    assert loaded["plan_version"] == 2


# ═══════════════════════════════════════════════════════════════
#  TC-SM07: 不同 session 互不干扰
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_different_sessions_isolated(test_db_session):
    saver = MySQLCheckpointSaver(session=test_db_session)
    session_a = str(uuid4())
    session_b = str(uuid4())

    state_a = make_test_agent_state(session_id=session_a, plan_version=1)
    state_b = make_test_agent_state(session_id=session_b, plan_version=3)

    await saver.put({"configurable": {"thread_id": session_a}}, state_a, {}, {})
    await saver.put({"configurable": {"thread_id": session_b}}, state_b, {}, {})

    loaded_a = await saver.get({"configurable": {"thread_id": session_a}})
    loaded_b = await saver.get({"configurable": {"thread_id": session_b}})

    assert loaded_a["plan_version"] == 1
    assert loaded_b["plan_version"] == 3


# ═══════════════════════════════════════════════════════════════
#  TC-SM08: 执行后发现需要重新规划 → planning
# ═══════════════════════════════════════════════════════════════

def test_route_execution_to_planning_when_needs_replan():
    state = AgentState(
        session_id="test",
        user_id="test",
        messages=[],
        slots={},
        current_phase="execution",
        needs_replan=True,
        task_statuses={"T001": "done"},
    )
    assert route_after_execution(state) == "planning"


# ═══════════════════════════════════════════════════════════════
#  TC-SM09: 所有任务完成 → reflection
# ═══════════════════════════════════════════════════════════════

def test_route_execution_to_reflection_when_all_done():
    state = AgentState(
        session_id="test",
        user_id="test",
        messages=[],
        slots={},
        current_phase="execution",
        needs_replan=False,
        task_statuses={"T001": "done", "T002": "done"},
    )
    assert route_after_execution(state) == "reflection"


# ═══════════════════════════════════════════════════════════════
#  TC-SM10: 部分任务未完成 → 继续执行
# ═══════════════════════════════════════════════════════════════

def test_route_execution_continues_when_tasks_pending():
    state = AgentState(
        session_id="test",
        user_id="test",
        messages=[],
        slots={},
        current_phase="execution",
        needs_replan=False,
        task_statuses={"T001": "done", "T002": "running"},
    )
    assert route_after_execution(state) == "execution"
