"""LangGraph State Machine — 完整四节点状态机。

节点：perception → planning → execution(stub) → reflection(stub)
路由：条件边基于状态判断，支持 Human-in-the-Loop 暂停。
持久化：MySQLCheckpointSaver 基于 sessions 表的 state_json 列。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Callable, TypedDict
from uuid import uuid4

from langgraph.graph import StateGraph, END

from backend.exceptions import PlanValidationError

logger = logging.getLogger("analytica.graph")


# ── Model factory ─────────────────────────────────────────────

def build_llm(model_key: str, *, request_timeout: int = 200):
    """Return a ChatOpenAI instance for the given model_key.

    Supported keys: 'qwen3-235b' (default), 'qwen3_5-122b', 'deepseek-r1'.
    DeepSeek-R1 omits the Qwen-specific enable_thinking flag.
    """
    from backend.config import get_settings
    from langchain_openai import ChatOpenAI

    s = get_settings()
    if model_key == "qwen3_5-122b":
        base, key, name = s.QWEN3_5_122B_API_BASE, s.QWEN3_5_122B_API_KEY or s.QWEN_API_KEY, s.QWEN3_5_122B_MODEL
    elif model_key == "deepseek-r1":
        base, key, name = s.DEEPSEEK_R1_API_BASE, s.DEEPSEEK_R1_API_KEY or s.QWEN_API_KEY, s.DEEPSEEK_R1_MODEL
    else:
        base, key, name = s.QWEN_API_BASE, s.QWEN_API_KEY, s.QWEN_MODEL

    kwargs: dict = dict(base_url=base, api_key=key, model=name, temperature=s.LLM_TEMPERATURE_DEFAULT, request_timeout=request_timeout)
    if not model_key.startswith("deepseek"):
        kwargs["extra_body"] = {"enable_thinking": False}
    return ChatOpenAI(**kwargs)


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
    replan_count: int

    # Reflection
    reflection: dict[str, Any] | None
    reflection_summary: dict[str, Any] | None

    # Control
    current_phase: str
    error: str | None
    web_search_enabled: bool  # 联网搜索开关

    # Multi-turn conversation (PR-1: Layer 1 + Layer 2)
    turn_index: int                          # 0-based turn counter
    turn_type: str                           # "new" | "continue" | "amend"
    analysis_history: list[dict[str, Any]]   # 每轮分析摘要（纯可序列化结构）
    plan_history: list[dict[str, Any]]       # 历史 plan（旧 analysis_plan 归档）


def make_initial_state(
    session_id: str,
    user_id: str,
    user_message: str,
    employee_id: str | None = None,
    web_search_enabled: bool = False,
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
        replan_count=0,
        reflection=None,
        reflection_summary=None,
        current_phase="perception",
        error=None,
        web_search_enabled=web_search_enabled,
        turn_index=0,
        turn_type="new",
        analysis_history=[],
        plan_history=[],
    )


# ── Multi-turn Helpers (V6: Layer 1 / Layer 2) ──────────────────
# V6 §4.4 — _classify_turn (keyword router) deleted; turn_type now
# comes from perception's MULTITURN_INTENT_PROMPT (LLM).


def _extract_last_user_message(state: dict) -> str:
    """Extract the most recent user message from state messages."""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return (msg.get("content") or "")[:200]
    return ""


def _extract_slot_snapshot(slots: dict) -> dict:
    """Extract a lightweight snapshot of slot values (no source/provenance)."""
    snapshot = {}
    for name, slot in slots.items():
        if isinstance(slot, dict) and slot.get("value") not in (None, ""):
            snapshot[name] = {"value": slot["value"]}
    return snapshot


def _collect_artifacts_from_context(
    execution_context: dict, tasks: list[dict]
) -> list[dict]:
    """Collect report artifacts from execution context."""
    artifacts = []
    for task in tasks:
        tid = task.get("task_id", "")
        if task.get("type") not in ("report_gen", "report"):
            continue
        result = execution_context.get(tid)
        if result is None:
            continue
        data = None
        if hasattr(result, "data"):
            data = result.data
        elif isinstance(result, dict):
            data = result.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(data, dict):
            for fmt in ("HTML", "PPTX", "DOCX", "PDF"):
                if fmt.lower() in str(data).lower():
                    artifacts.append({
                        "format": fmt,
                        "artifact_id": data.get("artifact_id", ""),
                    })
            if not artifacts and data.get("artifact_id"):
                artifacts.append({
                    "format": "unknown",
                    "artifact_id": data["artifact_id"],
                })
    return artifacts


def _build_turn_summary(state: dict) -> dict:
    """Build a serializable analysis_history entry from execution results."""
    plan = state.get("analysis_plan") or {}
    tasks = plan.get("tasks", [])
    context = state.get("execution_context") or {}

    data_snapshots = []
    key_findings = []

    for task in tasks:
        tid = task.get("task_id", "")
        result = context.get(tid)
        if result is None:
            continue

        data = None
        if hasattr(result, "data"):
            data = result.data
        elif isinstance(result, dict):
            data = result.get("data")

        if data is None:
            continue

        if task.get("type") == "data_fetch":
            import pandas as pd
            if isinstance(data, pd.DataFrame):
                df = data
                data_snapshots.append({
                    "task_id": tid,
                    "endpoint": task.get("params", {}).get("endpoint_id"),
                    "rows": len(df),
                    "columns": [str(c) for c in df.columns[:10]],
                    "sample": df.head(3).to_dict(orient="records"),
                    "params": task.get("params", {}),
                })
        elif task.get("type") in ("summary", "analysis"):
            text = data if isinstance(data, str) else str(data)[:300]
            if text.strip():
                key_findings.append(text[:200])

    artifacts = _collect_artifacts_from_context(context, tasks)

    completed_count = sum(
        1 for t in tasks
        if state.get("task_statuses", {}).get(t.get("task_id")) in ("done", "skipped")
    )
    failed_count = sum(
        1 for t in tasks
        if state.get("task_statuses", {}).get(t.get("task_id")) in ("failed", "error")
    )

    return {
        "turn": state.get("turn_index", 0),
        "turn_type": state.get("turn_type", "new"),
        "query": _extract_last_user_message(state),
        "plan_title": plan.get("title", ""),
        "data_snapshots": data_snapshots,
        "key_findings": key_findings[:5],
        "artifacts": artifacts,
        "slots_snapshot": _extract_slot_snapshot(state.get("slots", {})),
        "task_count": len(tasks),
        "completed_count": completed_count,
        "failed_count": failed_count,
    }


# ── History truncation ───────────────────────────────────────

MAX_HISTORY_TURNS = 5
MAX_SAMPLE_PER_TASK = 3
MAX_FINDINGS_PER_TURN = 5
MAX_FINDING_LENGTH = 200
MAX_SLOT_SNAPSHOT_ITEMS = 5

IMPORTANT_SLOTS = frozenset({
    "analysis_subject", "time_range", "domain",
    "output_format", "data_granularity",
})


def trim_analysis_history(history: list[dict]) -> list[dict]:
    """Trim analysis_history to fit within reasonable state_json size."""
    if len(history) > MAX_HISTORY_TURNS:
        history = history[-MAX_HISTORY_TURNS:]

    for turn in history:
        for snap in turn.get("data_snapshots", []):
            snap["sample"] = snap.get("sample", [])[:MAX_SAMPLE_PER_TASK]
            snap["columns"] = snap.get("columns", [])[:10]

        findings = turn.get("key_findings", [])
        turn["key_findings"] = [
            f[:MAX_FINDING_LENGTH] for f in findings[:MAX_FINDINGS_PER_TURN]
        ]

        slots = turn.get("slots_snapshot", {})
        if len(slots) > MAX_SLOT_SNAPSHOT_ITEMS:
            turn["slots_snapshot"] = {
                k: v for k, v in slots.items()
                if k in IMPORTANT_SLOTS
            }

    return history


def _load_workspace_manifest_for_state(state: dict) -> dict[str, Any]:
    """Load the on-disk SessionWorkspace manifest for the current state.

    Returns ``{"session_id": ..., "items": {}}`` when no workspace exists
    yet (first-turn / no session_id) so callers don't need to None-check.
    Failures are logged and degraded to an empty manifest — V6 prefers
    "show LLM nothing" to "crash the planning prompt"."""
    session_id = state.get("session_id") or ""
    empty = {"session_id": session_id, "items": {}}
    if not session_id:
        return empty
    try:
        from backend.config import get_settings
        from backend.memory.session_workspace import SessionWorkspace

        ws = SessionWorkspace(
            session_id=session_id,
            root=get_settings().WORKSPACE_ROOT,
        )
        return ws.manifest
    except Exception:
        logger.exception(
            "[multiturn_context] failed to load workspace manifest for %s",
            session_id,
        )
        return empty


def _build_multiturn_context_injection(state: dict) -> dict:
    """Build context dict for injection into perception/planning prompts."""
    history = state.get("analysis_history", [])
    if not history:
        return {}

    latest = history[-1]
    prev_snapshots = []
    for h in history:
        prev_snapshots.extend(h.get("data_snapshots", []))

    return {
        "turn_index": state.get("turn_index", 0),
        "turn_type": state.get("turn_type", "continue"),
        "latest_summary": latest,
        "all_key_findings": [
            f for h in history
            for f in h.get("key_findings", [])
        ],
        "prev_data_endpoints": list(set(
            s.get("endpoint") for s in prev_snapshots if s.get("endpoint")
        )),
        "prev_artifacts": latest.get("artifacts", []),
        "current_slots": _extract_slot_snapshot(state.get("slots", {})),
        "plan_history": state.get("plan_history", []),
        # V6 §5.4 — manifest snapshot drives data_ref reuse in planning.
        "workspace_manifest": _load_workspace_manifest_for_state(state),
    }


def _build_amend_plan(prev_state: dict, user_message: str):
    """Delegate to planning.build_amend_plan() for format add/replace.

    Returns AnalysisPlan, or None when format cannot be detected
    (caller should fall through to LLM planning).
    """
    from backend.agent.planning import build_amend_plan
    return build_amend_plan(prev_state, user_message)


def _append_turn_summary(state: dict) -> None:
    """Build turn summary and append to analysis_history in-place."""
    if state.get("analysis_plan") and state.get("execution_context"):
        try:
            summary = _build_turn_summary(state)
            history = list(state.get("analysis_history", []))
            history.append(summary)
            state["analysis_history"] = trim_analysis_history(history)
        except Exception:
            logger.exception("Failed to build turn summary")


def _should_append_turn_summary(state: dict) -> bool:
    """V6 §7.2.3 — guard against appending half-turns.

    A clarification round leaves perception incomplete (no
    structured_intent, no plan_confirmed, empty task_statuses); the
    same state would otherwise be appended to analysis_history both
    when the user gets the clarification question AND again when they
    finally answer it, polluting prompt context with duplicate
    half-summaries. Returns True only when all three layers ran.
    """
    if not state.get("structured_intent"):
        return False
    if not state.get("plan_confirmed"):
        return False
    if not state.get("task_statuses"):
        return False
    return True


def _open_session_workspace(state: dict):
    """Build a SessionWorkspace from the current state's session_id, or
    return None if we have no session (tests / probes). Failures are
    swallowed — the workspace is best-effort persistence and a missing
    one shouldn't block the chat path."""
    session_id = state.get("session_id")
    if not session_id:
        return None
    try:
        from backend.config import get_settings
        from backend.memory.session_workspace import SessionWorkspace

        return SessionWorkspace(
            session_id=session_id,
            root=get_settings().WORKSPACE_ROOT,
        )
    except Exception:
        logger.exception(
            "[graph] failed to open SessionWorkspace for %s", session_id,
        )
        return None


def _build_turn_boundary_event(state: dict) -> dict:
    """Build a turn_boundary event dict for the frontend.

    Emitted after each turn's execution completes, before state persistence.
    """
    analysis_history = state.get("analysis_history", [])
    last_turn = analysis_history[-1] if analysis_history else {}
    return {
        "event": "turn_boundary",
        "turn_index": state.get("turn_index", 0),
        "turn_type": state.get("turn_type", "new"),
        "plan_title": (state.get("analysis_plan") or {}).get("title", ""),
        "key_findings": last_turn.get("key_findings", [])[:3],
    }


# ── Node Implementations ─────────────────────────────────────

async def perception_node(state: AgentState) -> AgentState:
    """Perception node: extract slots and clarify intent."""
    from backend.agent.perception import run_perception
    from backend.tracing import trace_span

    # Outer phase span: groups the slot_fill / clarify sub-spans the engine
    # emits internally. Recorded output reflects whether the perception
    # round produced a usable intent or queued another clarification.
    raw_query = ""
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "user":
            raw_query = (msg.get("content") or "")[:80]
            break

    async with trace_span(
        "phase", "perception",
        task_name="感知阶段",
        phase="perception",
        input={
            "raw_query": raw_query,
            "clarification_round": state.get("clarification_round", 0),
            "filled_slots": [
                n for n, v in (state.get("slots") or {}).items()
                if isinstance(v, dict) and v.get("value") not in (None, "")
            ],
        },
    ) as phase_out:
        result = await run_perception(state)
        phase_out["intent_ready"] = bool(result.get("structured_intent"))
        phase_out["empty_required"] = list(result.get("empty_required_slots") or [])
        phase_out["target_slot"] = result.get("current_target_slot")
        return result


async def planning_node(state: AgentState) -> AgentState:
    """Planning node: generate analysis plan from structured intent.

    V6 §7.2.1 — plan_history archival is owned by run_stream's
    continuation branch, not this node. Here we only:
      * pass through if plan_confirmed (HitL resume)
      * auto-confirm an in-flight plan with unfinished tasks (also HitL
        resume)
      * otherwise call the LLM to generate a new plan
    """
    state["current_phase"] = "planning"

    # If plan already confirmed, pass through to execution
    if state.get("plan_confirmed"):
        return state

    # HitL resume: an in-flight plan with pending tasks → auto-confirm
    # so execution picks up where it left off. New plans for new turns
    # arrive here with analysis_plan=None (run_stream archived the
    # previous one), so this branch only fires on the resume path.
    if state.get("analysis_plan"):
        tasks = state["analysis_plan"].get("tasks", [])
        all_done = all(
            state.get("task_statuses", {}).get(t.get("task_id")) in ("done", "skipped")
            for t in tasks
        ) if tasks else True
        if not all_done:
            state["plan_confirmed"] = True
            return state
        # All tasks done already — drop the stale plan; the LLM call
        # below regenerates from the new intent.
        state["analysis_plan"] = None
        state["plan_confirmed"] = False

    intent = state.get("structured_intent")
    if intent is None:
        state["error"] = "No structured intent available for planning"
        return state

    try:
        from backend.agent.planning import (
            PlanningEngine,
            format_plan_as_markdown,
            is_simple_plan,
        )

        # ── 加载员工 profile 以获取白名单和搜索领域前缀 ──
        employee_id = state.get("employee_id")
        allowed_endpoints: frozenset[str] | None = None
        allowed_tools: frozenset[str] | None = None
        search_domain_prefix = ""
        search_public_hint = ""
        prompt_suffix = ""
        rule_hints: dict[str, str] | None = None

        if employee_id:
            try:
                from backend.employees.manager import EmployeeManager
                profile = EmployeeManager.get_instance().get_profile(employee_id)
                if profile:
                    allowed_endpoints = profile.get_endpoint_names()
                    allowed_tools = profile.get_tool_ids()
                    search_domain_prefix = profile.planning.search_domain_prefix or ""
                    search_public_hint = profile.planning.search_public_hint or ""
                    prompt_suffix = profile.planning.prompt_suffix or ""
                    rule_hints = profile.planning.rule_hints or {}
            except Exception:
                logger.warning(
                    "[planning_node] Failed to load profile for %s, using defaults",
                    employee_id,
                )

        llm = build_llm("qwen3-235b", request_timeout=200)
        engine = PlanningEngine(llm=llm, llm_timeout=120.0, max_retries=3)
        plan = await engine.generate_plan(
            intent,
            allowed_endpoints=allowed_endpoints,
            allowed_tools=allowed_tools,
            prompt_suffix=prompt_suffix,
            rule_hints=rule_hints,
            employee_id=employee_id,
            web_search_enabled=state.get("web_search_enabled", False),
            search_domain_prefix=search_domain_prefix,
            search_public_hint=search_public_hint,
            _multiturn_context=state.get("_multiturn_context"),
        )

        # ── V6 §6.1.3 — new-mode hard constraint ──
        # Before accepting the plan, verify that ``turn_type='new'``
        # plans don't reach back into the previous turn's manifest.
        # PlanValidationError surfaces the offending refs so the LLM
        # can fix them on the next iteration.
        try:
            from backend.agent.planning import validate_plan_against_workspace
            mt = state.get("_multiturn_context") or {}
            validate_plan_against_workspace(
                plan,
                turn_type=mt.get("turn_type") or state.get("turn_type", "continue"),
                current_turn_index=int(state.get("turn_index", 0)),
                workspace_manifest=mt.get("workspace_manifest"),
            )
        except PlanValidationError:
            # Re-raise as-is — the graph layer's outer handlers will
            # log it and surface a degraded plan / re-prompt path.
            # No silent fallback here (V6 "失败显式化").
            raise

        plan_dict = plan.model_dump()
        state["analysis_plan"] = plan_dict
        state["plan_version"] = plan.version

        # Surface planner-side drops / fallbacks as DegradationEvents
        # (cross-cutting channel — chat bubble, reflection, Trace tab).
        from backend.agent.degradation import DegradationEvent, record, SEVERITY_WARN
        for entry in plan.revision_log:
            phase = entry.get("phase")
            if phase == "validation" and entry.get("dropped"):
                record(state, DegradationEvent(
                    layer="planning",
                    severity=SEVERITY_WARN,
                    reason=(
                        f"规划阶段过滤了 {len(entry['dropped'])} 个任务"
                        f"（原 {entry.get('original_count', '?')} → 留 {entry.get('kept_count', '?')}）"
                    ),
                    affected={"dropped": entry["dropped"]},
                ))
            elif phase == "multi_round_stitch" and entry.get("failed_sections"):
                failed = entry["failed_sections"]
                record(state, DegradationEvent(
                    layer="planning",
                    severity=SEVERITY_WARN,
                    reason=(
                        f"多轮规划部分章节失败："
                        f"{len(failed)}/{entry.get('sections_total', '?')} 个章节未生成成功"
                        f"（已保留 {entry.get('sections_kept', '?')} 个）"
                    ),
                    affected={"failed_sections": failed},
                ))
            elif phase == "multi_round_fallback":
                record(state, DegradationEvent(
                    layer="planning",
                    severity=SEVERITY_WARN,
                    reason=(
                        f"多轮规划失败，已回退到单轮规划"
                        f"（{entry.get('error_type', 'Error')}: {entry.get('error', '')[:120]}）"
                    ),
                    affected={
                        "error_type": entry.get("error_type"),
                        "error": entry.get("error"),
                    },
                ))

        # Simple plans auto-execute: no confirmation card, graph flows
        # directly into execution on the next routing step.
        auto_confirmed = is_simple_plan(plan)
        state["plan_confirmed"] = auto_confirmed
        state["plan_auto_confirmed"] = auto_confirmed

        if auto_confirmed:
            # Terse acknowledgement — the full plan lives in the Agent
            # Inspector · Plan tab; duplicating a markdown task list in
            # the chat stream just adds visual noise for simple queries.
            est = plan.estimated_duration or sum(
                t.estimated_seconds for t in plan.tasks
            )
            duration_str = (
                f"约 {est // 60} 分钟" if est >= 60 else f"约 {est} 秒"
            )
            if not state.get("web_search_enabled"):
                search_status = " 联网搜索未开启。"
            elif not search_domain_prefix:
                search_status = " 联网搜索开关ON，但 search_domain_prefix 为空（员工 profile 缺失或未加载）。"
            else:
                search_status = f" 联网搜索已开启 (prefix: {search_domain_prefix[:30]}...)。"
            state["messages"].append({
                "role": "assistant",
                "content": (
                    f"已生成 **{len(plan.tasks)} 个任务** 的分析方案"
                    f"（预计 {duration_str}），自动开始执行。"
                    f"{search_status}"
                ),
            })
        else:
            # Complex plans still show the full markdown card so the user
            # can review and confirm/modify before execution.
            state["messages"].append({
                "role": "assistant",
                "content": format_plan_as_markdown(plan, auto_confirmed=False,
                                                    web_search_enabled=state.get("web_search_enabled", False),
                                                    search_domain_prefix=search_domain_prefix),
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
    """Reflection node: extract preferences, templates, and tool feedback."""
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
    terminal_states = {"done", "failed", "error", "skipped"}
    # "running"/"pending" are the only valid non-terminal values; anything
    # outside known states is treated as terminal (defensive guard against
    # unexpected status values causing an infinite execution loop).
    non_terminal = {"running", "pending"}
    all_terminal = all(
        v in terminal_states or v not in non_terminal
        for v in task_statuses.values()
    )
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
            "tool_feedback": len(rs.get("tool_feedback") or []),
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
    web_search_enabled: bool = False,
) -> AsyncGenerator[dict, None]:
    """Run the agent graph and stream state updates.

    多轮对话支持：从数据库加载上一轮状态（保留已填充的槽位、对话历史、
    追问轮次），追加新用户消息后继续图执行。图执行结束后将最终状态
    持久化回数据库，供下一轮使用。

    当 employee_id 提供时，使用员工专属图；否则使用通用单例图。

    `ws_callback` (Phase 2) — 若提供，execution.py 的任务更新 / 技能调用
    事件会直接推送到该回调，而非仅通过状态 yield 传出。不序列化到 DB。
    """
    # ── 搜索功能总开关归一化 ──
    from backend.config import get_settings
    if not get_settings().ENABLE_WEB_SEARCH:
        web_search_enabled = False

    from backend.database import get_session_factory
    from backend.memory.store import MemoryStore

    factory = get_session_factory()

    # 1. 从数据库加载上一轮会话状态
    async with factory() as db_session:
        store = MemoryStore(db_session)
        session_data = await store.get_session(session_id)

    prev_state = (session_data.get("state_json") if session_data else None) or {}

    # ── Control-phrase fast path ────────────────────────────
    # Plan-action buttons send these as regular chat messages; they must
    # not re-trigger perception (which would duplicate the "已理解..."
    # intent summary). "确认执行" with a pending plan short-circuits
    # directly into execution; others fall through to the graph.
    stripped_msg = (user_message or "").strip()
    is_confirm = stripped_msg == "确认执行"
    has_pending_plan = (
        bool(prev_state.get("analysis_plan"))
        and not prev_state.get("plan_confirmed")
    )
    if is_confirm and has_pending_plan:
        state = dict(prev_state)
        state.setdefault("messages", [])
        state["messages"].append({"role": "user", "content": user_message})
        state["plan_confirmed"] = True
        state["current_phase"] = "execution"
        state["error"] = None
        state["web_search_enabled"] = web_search_enabled

        # ── 搜索任务兜底注入 ──
        # "确认执行"快速路径跳过 planning 节点直接进入 execution，
        # 复用上一轮的 plan。如果用户在此之间开启了联网搜索，
        # plan 中可能缺少搜索任务，在此补上。
        if web_search_enabled and employee_id:
            try:
                from backend.employees.manager import EmployeeManager
                profile = EmployeeManager.get_instance().get_profile(employee_id)
                if profile:
                    prefix = profile.planning.search_domain_prefix or ""
                    if prefix:
                        plan = state.get("analysis_plan") or {}
                        tasks: list[dict] = plan.get("tasks", [])
                        has_search = any(
                            isinstance(t, dict) and t.get("type") == "search"
                            for t in tasks
                        )
                        if not has_search:
                            # 只用第一个领域关键词（公司名）+ 用户原始问题构建搜索 query
                            scope = prefix.split()[0]
                            query_str = f"{scope} {user_message}"
                            if len(query_str) > 200:
                                query_str = query_str[:200]
                            search_hint = profile.planning.search_public_hint or ""
                            search_task = {
                                "task_id": "G_SEARCH",
                                "type": "search",
                                "name": f"搜索：{user_message[:40]}",
                                "description": "互联网检索分析主题相关外部信息，为分析提供宏观背景和行业参考",
                                "depends_on": [],
                                "tool": "tool_web_search",
                                "params": {
                                    "query": query_str,
                                    "__search_domain_prefix__": prefix,
                                    "__search_public_hint__": search_hint,
                                    "__raw_query__": user_message,
                                },
                                "intent": (
                                    f"了解{user_message[:50]}的行业背景、政策环境和市场趋势，"
                                    f"补充外部信息以增强分析的全面性"
                                ),
                                "estimated_seconds": 10,
                            }
                            insert_at = 0
                            for i, t in enumerate(tasks):
                                if isinstance(t, dict) and t.get("type") == "data_fetch":
                                    insert_at = i + 1
                            tasks.insert(insert_at, search_task)
                            if "estimated_duration" in plan:
                                plan["estimated_duration"] = (
                                    plan.get("estimated_duration", 0) + 10
                                )
                            logger.info(
                                "[run_stream] confirm-execute fast path injected G_SEARCH"
                            )
            except Exception:
                logger.exception("Failed to inject search task in confirm-execute fast path")

        yield {"__meta__": {"initial_msg_count": len(state.get("messages", []))}}

        from backend.agent import ws_ctx
        from backend.agent.execution import execution_node as _exec_node
        token = ws_ctx.set_ws_callback(ws_callback)
        try:
            yield {
                "__thinking__": {
                    "kind": "phase",
                    "phase": "execution",
                    "payload": {"event": "phase_enter", "node": "execution"},
                },
            }
            state = await _exec_node(state)
            exit_payload = _summarize_node_exit("execution", state)
            if exit_payload:
                yield {
                    "__thinking__": {
                        "kind": "phase",
                        "phase": "execution",
                        "payload": {
                            "event": "phase_exit",
                            "node": "execution",
                            **exit_payload,
                        },
                    },
                }
            # Emit as if execution node yielded via graph so main.py's
            # existing event loop picks up task_statuses/messages.
            yield {"execution": state}
        finally:
            ws_ctx.reset_ws_callback(token)

        # V6 §7.2.3 / §7.3 — only finalize + append when the turn
        # actually completed (plan_confirmed + execution ran). The
        # confirm-execute fast path always satisfies this, but we keep
        # the guard for symmetry with the main graph path below.
        if _should_append_turn_summary(state):
            ws = _open_session_workspace(state)
            if ws is not None:
                try:
                    from backend.agent.execution import _finalize_turn
                    await _finalize_turn(ws, int(state.get("turn_index", 0)))
                except Exception:
                    logger.exception("[run_stream] finalize_turn failed")
            _append_turn_summary(state)
            yield _build_turn_boundary_event(state)
        try:
            safe_state = json.loads(
                json.dumps(state, ensure_ascii=False, default=str)
            )
            async with factory() as db_session:
                store = MemoryStore(db_session)
                await store.save_session_state(session_id, safe_state)
        except Exception:
            logger.exception("Failed to save session state for %s", session_id)
        return

    # 2. V6 §4.3 — first-turn vs continuation. turn_type now flows
    # back from perception's MULTITURN_INTENT_PROMPT (LLM); the legacy
    # _classify_turn router and amend fast-path are deleted.
    turn_index = prev_state.get("turn_index", 0)
    is_continuation = bool(prev_state.get("slots"))
    logger.info(
        "[run_stream] turn_index=%s is_continuation=%s session=%s",
        turn_index, is_continuation, session_id,
    )

    if not is_continuation:
        # 首轮 — discard prev state, keep messages for transcript display.
        old_messages = prev_state.get("messages", [])
        state = dict(make_initial_state(
            session_id, user_id, user_message,
            employee_id=employee_id,
            web_search_enabled=web_search_enabled,
        ))
        state["messages"] = old_messages + [{"role": "user", "content": user_message}]
        state["turn_index"] = 0
        # First-turn type is always 'new' (perception's MULTITURN prompt
        # only runs for continuations).
        state["turn_type"] = "new"
        state["plan_history"] = prev_state.get("plan_history", [])
    else:
        # 续接 — keep slots; perception writes turn_type back.
        state = dict(prev_state)
        state.setdefault("messages", []).append({"role": "user", "content": user_message})
        state["structured_intent"] = None
        state["current_target_slot"] = None
        state["current_phase"] = "perception"
        state["error"] = None
        state["web_search_enabled"] = web_search_enabled
        state["task_statuses"] = {}
        # turn_type stays None until perception classifies the turn.
        state["turn_type"] = None

        # V6 §7.2.1 — archive the previous plan exactly once on turn
        # entry. planning_node no longer archives; this is the single
        # source of truth for plan_history.
        if state.get("analysis_plan"):
            state.setdefault("plan_history", []).append(state["analysis_plan"])
            state["analysis_plan"] = None
            state["plan_confirmed"] = False

        # V6 §7.2.2 — turn_index advances only when the previous turn
        # truly completed (perception passed, plan confirmed, execution
        # ran). Clarification rounds keep the same turn_index until the
        # user finishes the missing slots.
        prev_completed = bool(
            prev_state.get("plan_confirmed")
            and prev_state.get("structured_intent") is not None
            and prev_state.get("task_statuses")
        )
        if prev_completed:
            state["turn_index"] = turn_index + 1
        else:
            state["turn_index"] = turn_index

        # V6 §7.3 — workspace turn_status hygiene. When a fresh turn
        # begins (turn_index advanced), mark any lingering ongoing
        # entries from the previous turn as abandoned. Mid-clarification
        # ongoing entries (same turn_index) are preserved.
        if prev_completed:
            ws = _open_session_workspace(state)
            if ws is not None:
                try:
                    from backend.agent.execution import _abandon_orphaned_turn
                    await _abandon_orphaned_turn(ws, turn_index)
                except Exception:
                    logger.exception("[run_stream] abandon_orphaned_turn failed")

        # 注入多轮上下文供 perception/planning 使用
        if state.get("analysis_history"):
            state["_multiturn_context"] = _build_multiturn_context_injection(state)

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
    from backend.agent.session_registry import get_registry
    _registry = get_registry()
    _registry.clear_cancel(session_id)
    cancel_event = _registry.get_cancel_event(session_id)

    # Run graph in a background Task so we can cancel it mid-LLM-call when
    # the user clicks "终止".  Without this, cancel_event is only checked
    # between node completions, meaning a 30-60s planning LLM call can't be
    # interrupted until it naturally finishes.
    _event_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def _graph_producer() -> None:
        try:
            async for ev in graph.astream(state):
                await _event_queue.put(("event", ev))
        except asyncio.CancelledError:
            pass
        finally:
            await _event_queue.put(("done", None))

    # set_ws_callback MUST happen before create_task: asyncio.create_task copies
    # the current context at task-creation time, so setting the contextvar after
    # the task is created leaves _graph_producer (and every graph node it runs)
    # with ws_callback=None, silently dropping all span emissions.
    token = ws_ctx.set_ws_callback(ws_callback)
    _producer = asyncio.create_task(_graph_producer())
    _cancelled_early = False
    final_state = dict(state)
    visited_nodes: set[str] = set()
    try:
        while True:
            # Poll with 0.3s timeout so cancel_event is checked regularly
            # even while the graph is blocked inside a long LLM call.
            try:
                kind, event = await asyncio.wait_for(_event_queue.get(), timeout=0.3)
            except asyncio.TimeoutError:
                if cancel_event.is_set():
                    _producer.cancel()
                    _cancelled_early = True
                    break
                continue

            if kind == "done":
                break

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
                # 节点退出事件 + 节点产物摘要
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

            if cancel_event.is_set():
                _producer.cancel()
                _cancelled_early = True
                break
    finally:
        ws_ctx.reset_ws_callback(token)
        if not _producer.done():
            _producer.cancel()
        await asyncio.gather(_producer, return_exceptions=True)

    if _cancelled_early:
        _registry.clear_cancel(session_id)
        if ws_callback:
            try:
                await ws_callback({"event": "cancelled"})
            except Exception:
                pass
        return

    # 6. V6 §7.2.3 / §7.3 — only finalize the turn + append summary +
    # emit turn_boundary when perception, planning AND execution all
    # ran. Mid-clarification states still persist (so the next user
    # message picks up context) but do NOT touch analysis_history /
    # workspace turn_status — preventing duplicate half-summaries and
    # turn-state pollution.
    if _should_append_turn_summary(final_state):
        ws = _open_session_workspace(final_state)
        if ws is not None:
            try:
                from backend.agent.execution import _finalize_turn
                await _finalize_turn(ws, int(final_state.get("turn_index", 0)))
            except Exception:
                logger.exception("[run_stream] finalize_turn failed")
        _append_turn_summary(final_state)
        yield _build_turn_boundary_event(final_state)
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
