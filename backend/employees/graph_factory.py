"""员工图工厂 — 为指定 EmployeeProfile 构建参数化的 LangGraph。

核心思路：通过 Python 闭包将 profile / allowed_endpoints / allowed_tools
注入到每个节点函数中，节点内部逻辑几乎不变。
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from backend.employees.profile import EmployeeProfile

logger = logging.getLogger("analytica.employees.graph_factory")


def _ensure_search_task_in_plan(plan: dict[str, Any], search_domain_prefix: str) -> bool:
    """兜底注入搜索任务到 plan dict 中（幂等：已有则跳过）。

    返回 True 表示新注入了任务。
    """
    if not search_domain_prefix:
        return False

    tasks: list[dict] = plan.get("tasks", [])
    if any(isinstance(t, dict) and t.get("type") == "search" for t in tasks):
        return False  # 已有搜索任务，不重复注入

    title = plan.get("title", "") or "数据分析"
    query = f"{search_domain_prefix} {title}"
    if len(query) > 200:
        query = query[:200]

    search_task = {
        "task_id": "G_SEARCH",
        "type": "search",
        "name": f"搜索：{title[:40]}",
        "description": "互联网检索分析主题相关外部信息，为分析提供宏观背景和行业参考",
        "depends_on": [],
        "tool": "tool_web_search",
        "params": {
            "query": query,
            "__search_domain_prefix__": search_domain_prefix,
        },
        "intent": (
            f"了解{title[:50]}的行业背景、政策环境和市场趋势，"
            f"补充外部信息以增强分析的全面性"
        ),
        "estimated_seconds": 10,
    }

    # 插入到最后一个 data_fetch 任务之后
    insert_at = 0
    for i, t in enumerate(tasks):
        if isinstance(t, dict) and t.get("type") == "data_fetch":
            insert_at = i + 1
    tasks.insert(insert_at, search_task)

    if "estimated_duration" in plan:
        plan["estimated_duration"] = plan.get("estimated_duration", 0) + 10

    return True


def build_employee_graph(profile: EmployeeProfile) -> Any:
    """为指定员工构建参数化的 LangGraph，返回 CompiledGraph。"""
    from backend.agent.graph import AgentState, route_after_perception, route_after_planning, route_after_execution

    allowed_endpoints = profile.get_endpoint_names()
    allowed_tools = profile.get_tool_ids()
    planning_prompt_suffix = profile.planning.prompt_suffix or ""
    planning_rule_hints = profile.planning.rule_hints or {}

    # ── 闭包节点 ──

    async def emp_perception_node(state: AgentState) -> AgentState:
        from backend.agent.perception import run_perception
        return await run_perception(state, profile=profile)

    async def emp_planning_node(state: AgentState) -> AgentState:
        """与 graph.py 中 planning_node 逻辑相同，但注入员工域过滤。"""
        state["current_phase"] = "planning"

        if state.get("plan_confirmed"):
            return state

        # Auto-confirm existing plan from previous turn (loaded from DB)
        if state.get("analysis_plan"):
            state["plan_confirmed"] = True
            # ── 搜索任务兜底注入：已复用旧 plan，若开启了搜索则补上 ──
            if state.get("web_search_enabled") and profile.planning.search_domain_prefix:
                injected = _ensure_search_task_in_plan(
                    state["analysis_plan"],
                    profile.planning.search_domain_prefix,
                )
                if injected:
                    logger.info(
                        "[%s] planning auto-confirm injected G_SEARCH (plan reused from previous turn)",
                        profile.employee_id,
                    )
            return state

        intent = state.get("structured_intent")
        if intent is None:
            state["error"] = "No structured intent available for planning"
            return state

        # ── 根据联网搜索开关动态过滤 allowed_tools ──
        effective_tools = allowed_tools
        if not state.get("web_search_enabled", False):
            effective_tools = allowed_tools - {"tool_web_search"}

        try:
            from backend.agent.planning import PlanningEngine, format_plan_as_markdown
            from backend.agent.graph import build_llm
            llm = build_llm("qwen3-235b", request_timeout=200)
            engine = PlanningEngine(llm=llm, llm_timeout=120.0, max_retries=3)
            plan = await engine.generate_plan(
                intent,
                allowed_endpoints=allowed_endpoints,
                allowed_tools=effective_tools,
                prompt_suffix=planning_prompt_suffix,
                rule_hints=planning_rule_hints,
                employee_id=profile.employee_id,
                web_search_enabled=state.get("web_search_enabled", False),
                search_domain_prefix=profile.planning.search_domain_prefix or "",
            )

            plan_dict = plan.model_dump()
            state["analysis_plan"] = plan_dict
            state["plan_confirmed"] = False
            state["plan_version"] = plan.version

            # Surface validator drops (recorded in plan.revision_log) as
            # DegradationEvents on state so downstream layers / chat bubble
            # can show what the validator silently filtered.
            from backend.agent.degradation import DegradationEvent, record, summarize, SEVERITY_WARN
            for entry in plan.revision_log:
                if entry.get("phase") == "validation" and entry.get("dropped"):
                    record(state, DegradationEvent(
                        layer="planning",
                        severity=SEVERITY_WARN,
                        reason=(
                            f"规划阶段过滤了 {len(entry['dropped'])} 个任务"
                            f"（原 {entry.get('original_count', '?')} → 留 {entry.get('kept_count', '?')}）"
                        ),
                        affected={"dropped": entry["dropped"]},
                    ))

            md = format_plan_as_markdown(plan,
                                          web_search_enabled=state.get("web_search_enabled", False),
                                          search_domain_prefix=profile.planning.search_domain_prefix or "")
            degradation_summary = summarize(state)
            if degradation_summary:
                md = f"{md}\n\n---\n{degradation_summary}"
            state["messages"].append({
                "role": "assistant",
                "content": md,
            })

        except Exception as e:
            logger.exception("[%s] Planning node error: %s", profile.employee_id, e)
            state["error"] = str(e)
            state["messages"].append({
                "role": "assistant",
                "content": f"规划生成失败：{e}",
            })

        return state

    async def emp_execution_node(state: AgentState) -> AgentState:
        from backend.agent.execution import execution_node as _exec_node

        effective_tools = allowed_tools
        if not state.get("web_search_enabled", False):
            effective_tools = allowed_tools - {"tool_web_search"}

        # ── 搜索任务兜底注入 + 领域前缀注入 ──
        # 执行节点是唯一必定执行的节点——无论计划是新生成、被复用（多轮
        # 状态恢复）、还是"确认执行"快速路径跳过 planning，都会经过这里。
        # 因此在此做兜底确保：只要搜索开关打开，plan 中必有搜索任务。
        search_prefix = profile.planning.search_domain_prefix or ""
        if search_prefix and state.get("web_search_enabled") and state.get("analysis_plan"):
            injected = _ensure_search_task_in_plan(state["analysis_plan"], search_prefix)
            if injected:
                logger.info(
                    "[%s] execution node injected G_SEARCH (plan reused without regeneration)",
                    profile.employee_id,
                )

            # 注入 domain prefix 到所有搜索任务 params 中
            tasks: list[dict] = state["analysis_plan"].get("tasks", [])
            for t in tasks:
                if isinstance(t, dict) and t.get("type") == "search":
                    t.setdefault("params", {})
                    t["params"]["__search_domain_prefix__"] = search_prefix

        return await _exec_node(state, allowed_tools=effective_tools)

    async def emp_reflection_node(state: AgentState) -> AgentState:
        """反思节点 — 复用通用逻辑。"""
        state["current_phase"] = "reflection"
        state["messages"].append({
            "role": "assistant",
            "content": "[Reflection] Phase 4 stub: reflection placeholder.",
        })
        return state

    # ── 组装图 ──

    graph = StateGraph(AgentState)

    graph.add_node("perception", emp_perception_node)
    graph.add_node("planning", emp_planning_node)
    graph.add_node("execution", emp_execution_node)
    graph.add_node("reflection", emp_reflection_node)

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
    # 反思节点暂时禁用
    graph.add_edge("reflection", END)

    logger.info(
        "[%s] Built employee graph (endpoints=%d, tools=%d)",
        profile.employee_id, len(allowed_endpoints), len(allowed_tools),
    )

    return graph.compile()
