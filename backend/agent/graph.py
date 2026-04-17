"""LangGraph State Machine — 完整四节点状态机。

节点：perception → planning → execution(stub) → reflection(stub)
路由：条件边基于状态判断，支持 Human-in-the-Loop 暂停。
持久化：MySQLCheckpointSaver 基于 sessions 表的 state_json 列。
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, TypedDict
from uuid import uuid4

from langgraph.graph import StateGraph, END

logger = logging.getLogger("analytica.graph")


# ── Agent State ──────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    """State shared across all graph nodes."""

    session_id: str
    user_id: str
    employee_id: str | None  # 员工 ID（可选，用于日志追踪）
    messages: list[dict[str, str]]

    # Perception
    slots: dict[str, dict[str, Any]]
    current_target_slot: str | None
    empty_required_slots: list[str]
    structured_intent: dict[str, Any] | None
    clarification_round: int

    # Planning
    analysis_plan: dict[str, Any] | None
    plan_confirmed: bool
    plan_version: int

    # Execution (Phase 3 stub)
    task_statuses: dict[str, str]
    execution_context: dict[str, Any] | None
    needs_replan: bool

    # Reflection (Phase 4 stub)
    reflection: dict[str, Any] | None

    # Control
    current_phase: str
    error: str | None


def make_initial_state(
    session_id: str,
    user_id: str,
    user_message: str,
    employee_id: str | None = None,
) -> AgentState:
    """Create the initial agent state for a new conversation turn."""
    return AgentState(
        session_id=session_id,
        user_id=user_id,
        employee_id=employee_id,
        messages=[{"role": "user", "content": user_message}],
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


# ── Node Implementations ─────────────────────────────────────

async def perception_node(state: AgentState) -> AgentState:
    """Perception node: extract slots and clarify intent."""
    from backend.agent.perception import run_perception
    return await run_perception(state)


async def planning_node(state: AgentState) -> AgentState:
    """Planning node: generate analysis plan from structured intent.

    If plan_confirmed is True (resuming after confirmation), skip generation.
    """
    state["current_phase"] = "planning"

    # If plan already confirmed, pass through to execution
    if state.get("plan_confirmed"):
        return state

    intent = state.get("structured_intent")
    if intent is None:
        state["error"] = "No structured intent available for planning"
        return state

    try:
        from backend.config import get_settings
        from langchain_openai import ChatOpenAI
        from backend.agent.planning import PlanningEngine, format_plan_as_markdown

        settings = get_settings()
        llm = ChatOpenAI(
            base_url=settings.QWEN_API_BASE,
            api_key=settings.QWEN_API_KEY,
            model=settings.QWEN_MODEL,
            temperature=0.1,
            request_timeout=120,
        )

        engine = PlanningEngine(llm=llm, llm_timeout=120.0, max_retries=3)
        plan = await engine.generate_plan(intent)

        plan_dict = plan.model_dump()
        state["analysis_plan"] = plan_dict
        state["plan_confirmed"] = False
        state["plan_version"] = plan.version

        # Generate markdown display
        md = format_plan_as_markdown(plan)
        state["messages"].append({
            "role": "assistant",
            "content": md,
        })

    except Exception as e:
        logger.exception("Planning node error: %s", e)
        state["error"] = str(e)
        state["messages"].append({
            "role": "assistant",
            "content": f"规划生成失败：{e}",
        })

    return state


async def execution_node(state: AgentState) -> AgentState:
    """Execution node: runs the analysis plan tasks."""
    from backend.agent.execution import execution_node as _exec_node
    return await _exec_node(state)


async def reflection_node(state: AgentState) -> AgentState:
    """Reflection node stub (Phase 4)."""
    state["current_phase"] = "reflection"
    state["messages"].append({
        "role": "assistant",
        "content": "[Reflection] Phase 4 stub: reflection placeholder.",
    })
    return state


# ── Routing Functions ────────────────────────────────────────

def route_after_perception(state: AgentState) -> str:
    """Route after perception: clarify or proceed to planning."""
    if state.get("structured_intent") is not None:
        return "planning"
    return END  # Waiting for user response to clarification


def route_after_planning(state: AgentState) -> str:
    """Route after planning: wait for confirmation or execute.

    Human-in-the-Loop: if plan_confirmed is False, end the graph
    (external API call will resume with confirmation).
    """
    if state.get("plan_confirmed"):
        return "execution"
    return END


def route_after_execution(state: AgentState) -> str:
    """Route after execution: replan, continue, or reflect."""
    if state.get("needs_replan"):
        return "planning"
    task_statuses = state.get("task_statuses", {})
    all_done = task_statuses and all(v == "done" for v in task_statuses.values())
    if all_done:
        return "reflection"
    return "execution"


def after_reflection(state: AgentState) -> str:
    return END


# ── Build Graph ──────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Build and compile the LangGraph state machine."""
    graph = StateGraph(AgentState)

    graph.add_node("perception", perception_node)
    graph.add_node("planning", planning_node)
    graph.add_node("execution", execution_node)
    graph.add_node("reflection", reflection_node)

    graph.set_entry_point("perception")

    graph.add_conditional_edges(
        "perception",
        route_after_perception,
        {"planning": "planning", END: END},
    )
    graph.add_conditional_edges(
        "planning",
        route_after_planning,
        {"execution": "execution", END: END},
    )
    graph.add_conditional_edges(
        "execution",
        route_after_execution,
        {"planning": "planning", "execution": "execution", "reflection": "reflection"},
    )
    graph.add_edge("reflection", END)

    return graph


compiled_graph = None


def get_compiled_graph():
    """Get or compile the graph singleton."""
    global compiled_graph
    if compiled_graph is None:
        compiled_graph = build_graph().compile()
    return compiled_graph


async def run_stream(
    session_id: str,
    user_id: str,
    user_message: str,
    employee_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Run the agent graph and stream state updates.

    当 employee_id 提供时，委托给 EmployeeManager 使用员工专属图；
    否则使用通用单例图（向后兼容）。
    """
    if employee_id:
        from backend.employees.manager import EmployeeManager
        manager = EmployeeManager.get_instance()
        async for event in manager.run_employee_stream(
            employee_id, session_id, user_id, user_message,
        ):
            yield event
    else:
        graph = get_compiled_graph()
        initial = make_initial_state(session_id, user_id, user_message)
        async for event in graph.astream(initial):
            yield event


# ── MySQL Checkpoint Saver ───────────────────────────────────

class MySQLCheckpointSaver:
    """Checkpoint saver using MySQL sessions table.

    Stores serialized state in sessions.state_json column.
    Uses INSERT ... ON DUPLICATE KEY UPDATE for upsert.
    """

    def __init__(self, session=None):
        self.session = session

    async def put(
        self,
        config: dict,
        checkpoint: dict,
        metadata: dict | None = None,
        new_versions: dict | None = None,
    ) -> dict:
        """Serialize and persist checkpoint to MySQL."""
        from sqlalchemy import text

        thread_id = config.get("configurable", {}).get("thread_id", "")
        state_json = json.dumps(checkpoint, ensure_ascii=False, default=str)

        await self.session.execute(
            text("""
                INSERT INTO sessions (session_id, user_id, state_json)
                VALUES (:sid, :uid, :state)
                ON DUPLICATE KEY UPDATE state_json = :state, updated_at = NOW()
            """),
            {"sid": thread_id, "uid": checkpoint.get("user_id", "system"), "state": state_json},
        )
        await self.session.commit()
        return config

    async def get(self, config: dict) -> dict | None:
        """Load checkpoint from MySQL."""
        from sqlalchemy import text

        thread_id = config.get("configurable", {}).get("thread_id", "")
        result = await self.session.execute(
            text("SELECT state_json FROM sessions WHERE session_id = :sid"),
            {"sid": thread_id},
        )
        row = result.first()
        if row is None:
            return None

        state_json = row[0]
        if isinstance(state_json, str):
            return json.loads(state_json)
        return state_json if isinstance(state_json, dict) else None

    async def list(self, config: dict, **kwargs) -> list:
        """List checkpoints (MVP: returns at most one)."""
        checkpoint = await self.get(config)
        if checkpoint is None:
            return []
        return [{"config": config, "checkpoint": checkpoint}]
