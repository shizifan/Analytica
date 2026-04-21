"""LangGraph State Machine — 完整四节点状态机。

节点：perception → planning → execution(stub) → reflection(stub)
路由：条件边基于状态判断，支持 Human-in-the-Loop 暂停。
持久化：MySQLCheckpointSaver 基于 sessions 表的 state_json 列。
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Callable, TypedDict
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

    # Reflection
    reflection: dict[str, Any] | None
    reflection_summary: dict[str, Any] | None

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
        reflection_summary=None,
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
    If analysis_plan already exists from a previous turn (loaded from DB),
    auto-confirm and proceed to execution without regenerating.
    """
    state["current_phase"] = "planning"

    # If plan already confirmed, pass through to execution
    if state.get("plan_confirmed"):
        return state

    # Auto-confirm existing plan from previous turn (loaded from DB)
    if state.get("analysis_plan"):
        state["plan_confirmed"] = True
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
            extra_body={"enable_thinking": False},
        )

        engine = PlanningEngine(llm=llm, llm_timeout=120.0, max_retries=3)
        plan = await engine.generate_plan(
            intent,
            employee_id=state.get("employee_id"),
        )

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
    """Reflection node: extract preferences, templates, and skill feedback."""
    from backend.agent.reflection import reflection_node as _reflect_node
    return await _reflect_node(state)


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
    """Route after execution: replan, continue, or end."""
    if state.get("needs_replan"):
        return "planning"
    task_statuses = state.get("task_statuses", {})
    if not task_statuses:
        return END
    # Exit when all tasks reached a terminal state (done/failed/error/skipped)
    terminal_states = {"done", "failed", "error", "skipped"}
    all_terminal = all(v in terminal_states for v in task_statuses.values())
    if all_terminal:
        return END
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
        {"planning": "planning", "execution": "execution", END: END},
    )
    # 反思节点暂时禁用，保留节点定义供后续启用
    graph.add_edge("reflection", END)

    return graph


compiled_graph = None


# ── Phase 3.5: node-exit summaries for the thinking stream ─────────────

def _summarize_node_exit(
    node_name: str, node_state: dict | None,
) -> dict | None:
    """Build a compact payload describing what a node produced.

    Returned dict is merged into the `phase_exit` thinking event; keep
    fields short and UI-friendly (no raw DataFrames or prompt dumps).
    """
    if not node_state:
        return None

    if node_name == "perception":
        slots = node_state.get("slots") or {}
        filled = sum(
            1
            for v in slots.values()
            if isinstance(v, dict) and v.get("value") not in (None, "")
        )
        return {
            "slot_total": len(slots),
            "slot_filled": filled,
            "intent_ready": bool(node_state.get("structured_intent")),
            "clarification_round": node_state.get("clarification_round", 0),
            "asking_slot": node_state.get("current_target_slot"),
        }

    if node_name == "planning":
        plan = node_state.get("analysis_plan") or {}
        tasks = plan.get("tasks") or []
        return {
            "plan_ready": bool(plan),
            "plan_version": plan.get("version"),
            "task_count": len(tasks),
            "estimated_duration": plan.get("estimated_duration"),
        }

    if node_name == "execution":
        statuses = node_state.get("task_statuses") or {}
        counter = {"done": 0, "failed": 0, "skipped": 0, "running": 0}
        for s in statuses.values():
            counter[s] = counter.get(s, 0) + 1
        return {
            "task_total": len(statuses),
            **counter,
            "needs_replan": bool(node_state.get("needs_replan")),
        }

    if node_name == "reflection":
        rs = node_state.get("reflection_summary") or {}
        return {
            "preferences": len(rs.get("user_preferences") or []),
            "templates": 1 if rs.get("analysis_template") else 0,
            "skill_feedback": len(rs.get("skill_feedback") or []),
        }

    return None


def _detect_decision(
    node_name: str, node_state: dict | None, prev_phase: str | None,
) -> dict | None:
    """Emit a `decision` thinking event at key branch points."""
    if not node_state:
        return None

    if node_name == "perception":
        # Clarification vs proceed
        if node_state.get("current_target_slot"):
            return {
                "branch": "clarify",
                "reason": f"追问槽位 {node_state['current_target_slot']}",
            }
        if node_state.get("structured_intent"):
            return {"branch": "proceed", "reason": "意图就绪 → planning"}

    if node_name == "planning":
        plan = node_state.get("analysis_plan") or {}
        if plan.get("tasks"):
            return {
                "branch": "plan_ready",
                "reason": f"{len(plan['tasks'])} 个任务 · v{plan.get('version')}",
            }

    if node_name == "execution":
        if node_state.get("needs_replan"):
            return {"branch": "replan", "reason": "数据不足触发重新规划"}

    return None


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
    ws_callback: Callable[[dict], Any] | None = None,
) -> AsyncGenerator[dict, None]:
    """Run the agent graph and stream state updates.

    多轮对话支持：从数据库加载上一轮状态（保留已填充的槽位、对话历史、
    追问轮次），追加新用户消息后继续图执行。图执行结束后将最终状态
    持久化回数据库，供下一轮使用。

    当 employee_id 提供时，使用员工专属图；否则使用通用单例图。

    `ws_callback` (Phase 2) — 若提供，execution.py 的任务更新 / 技能调用
    事件会直接推送到该回调，而非仅通过状态 yield 传出。不序列化到 DB。
    """
    from backend.database import get_session_factory
    from backend.memory.store import MemoryStore

    factory = get_session_factory()

    # 1. 从数据库加载上一轮会话状态
    async with factory() as db_session:
        store = MemoryStore(db_session)
        session_data = await store.get_session(session_id)

    prev_state = (session_data.get("state_json") if session_data else None) or {}

    # 2. 构建本轮状态：有历史槽位则续接，否则全新开始
    if prev_state.get("slots"):
        state: dict[str, Any] = dict(prev_state)
        state.setdefault("messages", [])
        state["messages"].append({"role": "user", "content": user_message})
        # 重置每轮控制字段，让 perception 重新评估
        state["structured_intent"] = None
        state["current_target_slot"] = None
        state["current_phase"] = "perception"
        state["error"] = None
    else:
        state = dict(
            make_initial_state(session_id, user_id, user_message, employee_id=employee_id)
        )

    # 3. 获取对应的编译图
    if employee_id:
        from backend.employees.manager import EmployeeManager
        manager = EmployeeManager.get_instance()
        graph = manager.get_graph(employee_id)
    else:
        graph = get_compiled_graph()

    # 4. 通知调用方当前消息基线（避免重发历史消息）
    yield {"__meta__": {"initial_msg_count": len(state.get("messages", []))}}

    # 5. 执行图并流式返回事件，同时捕获最终状态 + 节点边界思维流事件
    #    Phase 3.5: ws_callback 通过 contextvars 暴露给所有节点（避免把
    #    可调用对象写进 state 导致的 TypedDict 过滤与序列化问题）。
    from backend.agent import ws_ctx
    token = ws_ctx.set_ws_callback(ws_callback)
    final_state = dict(state)
    visited_nodes: set[str] = set()
    try:
        async for event in graph.astream(state):
            for node_name, node_state in event.items():
                prev_phase = final_state.get("current_phase")
                final_state.update(node_state)
                # 节点进入事件
                if node_name not in visited_nodes:
                    visited_nodes.add(node_name)
                    yield {
                        "__thinking__": {
                            "kind": "phase",
                            "phase": node_name,
                            "payload": {
                                "event": "phase_enter",
                                "node": node_name,
                            },
                        }
                    }
                # 节点退出事件 + 节点产物摘要（Phase 3.5）
                exit_payload = _summarize_node_exit(node_name, node_state)
                if exit_payload:
                    yield {
                        "__thinking__": {
                            "kind": "phase",
                            "phase": node_name,
                            "payload": {
                                "event": "phase_exit",
                                "node": node_name,
                                **exit_payload,
                            },
                        }
                    }
                # 关键分叉决策
                decision = _detect_decision(node_name, node_state, prev_phase)
                if decision:
                    yield {"__thinking__": {"kind": "decision", "phase": node_name, "payload": decision}}
            yield event
    finally:
        ws_ctx.reset_ws_callback(token)

    # 6. 最终状态 → DB；剥离非序列化字段
    try:
        safe_state = json.loads(
            json.dumps(final_state, ensure_ascii=False, default=str)
        )
        async with factory() as db_session:
            store = MemoryStore(db_session)
            await store.save_session_state(session_id, safe_state)
    except Exception:
        logger.exception("Failed to save session state for %s", session_id)


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
