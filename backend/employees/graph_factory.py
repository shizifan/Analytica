"""员工图工厂 — 为指定 EmployeeProfile 构建参数化的 LangGraph。

核心思路：通过 Python 闭包将 profile / allowed_endpoints / allowed_skills
注入到每个节点函数中，节点内部逻辑几乎不变。
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from backend.employees.profile import EmployeeProfile

logger = logging.getLogger("analytica.employees.graph_factory")


def build_employee_graph(profile: EmployeeProfile) -> Any:
    """为指定员工构建参数化的 LangGraph，返回 CompiledGraph。"""
    from backend.agent.graph import AgentState, route_after_perception, route_after_planning, route_after_execution

    allowed_endpoints = profile.get_endpoint_names()
    allowed_skills = profile.get_skill_ids()
    planning_prompt_suffix = profile.planning.prompt_suffix or ""

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
                allowed_endpoints=allowed_endpoints,
                allowed_skills=allowed_skills,
                prompt_suffix=planning_prompt_suffix,
                employee_id=profile.employee_id,
            )

            plan_dict = plan.model_dump()
            state["analysis_plan"] = plan_dict
            state["plan_confirmed"] = False
            state["plan_version"] = plan.version

            md = format_plan_as_markdown(plan)
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
        return await _exec_node(state, allowed_skills=allowed_skills)

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
        "[%s] Built employee graph (endpoints=%d, skills=%d)",
        profile.employee_id, len(allowed_endpoints), len(allowed_skills),
    )

    return graph.compile()
