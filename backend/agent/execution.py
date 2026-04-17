"""Execution Node — executes tasks from AnalysisPlan with parallel support.

Features:
- Topological sort of task DAG
- Parallel execution (max 3 concurrent) via asyncio.gather
- Per-task timeout (estimated_seconds * 3)
- Single task failure does not block others
- Dynamic re-planning on low data volume
- WebSocket push support (optional callback)
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from backend.models.schemas import TaskItem
from backend.skills.base import SkillInput, SkillOutput, skill_executor
from backend.skills.registry import SkillRegistry

logger = logging.getLogger("analytica.execution")

MAX_CONCURRENT = 3


# ── data_fetch 错误诊断 ─────────────────────────────────────


def classify_data_fetch_error(error_message: str) -> str:
    """将 data_fetch 错误分类为根因类型。"""
    if not error_message:
        return "UNKNOWN"
    if "未知的端点" in error_message:
        return "LLM_HALLUCINATION"
    if "无对应 API 路径" in error_message:
        return "ENDPOINT_NOT_MAPPED"
    if "缺少必填参数" in error_message:
        return "MISSING_PARAMS"
    if "401" in error_message or "认证失败" in error_message:
        return "AUTH_ERROR"
    if any(k in error_message for k in ("500", "502", "503", "服务端错误")):
        return "SERVER_ERROR"
    if any(k in error_message for k in ("400", "404", "客户端错误")):
        return "CLIENT_ERROR"
    if "超时" in error_message:
        return "TIMEOUT"
    if "依赖任务失败" in error_message:
        return "CASCADE_FAILURE"
    return "UNKNOWN"


@dataclass
class DataFetchCheckResult:
    """data_fetch 阈值检查结果。"""
    passed: bool
    total_count: int
    success_count: int
    failed_count: int
    required_count: int
    tier: str  # "none" / "small" / "medium" / "large"
    failures: list[dict] = field(default_factory=list)


def check_data_fetch_threshold(
    tasks: list[TaskItem],
    task_statuses: dict[str, str],
    execution_context: dict[str, SkillOutput] | None = None,
) -> DataFetchCheckResult:
    """检查 data_fetch 任务的成功率是否达标。

    阈值分级:
    - small  (1-3): 至少 1 个成功
    - medium (4-6): 允许最多 2 个失败
    - large  (7+):  至少 70% 成功
    """
    df_tasks = [t for t in tasks if t.type == "data_fetch"]
    total = len(df_tasks)

    if total == 0:
        return DataFetchCheckResult(
            passed=True, total_count=0, success_count=0,
            failed_count=0, required_count=0, tier="none",
        )

    success_count = sum(
        1 for t in df_tasks if task_statuses.get(t.task_id) == "done"
    )
    failed_count = total - success_count

    # 收集每个失败任务的详情
    failures = []
    for t in df_tasks:
        if task_statuses.get(t.task_id) != "done":
            error_msg = ""
            if execution_context and t.task_id in execution_context:
                output = execution_context[t.task_id]
                error_msg = output.error_message or ""
            endpoint_id = t.params.get("endpoint_id", t.task_id)
            failures.append({
                "task_id": t.task_id,
                "endpoint_id": endpoint_id,
                "error_message": error_msg,
                "error_type": classify_data_fetch_error(error_msg),
            })

    # 分级阈值
    if total <= 3:
        tier = "small"
        required = 1
    elif total <= 6:
        tier = "medium"
        required = max(1, total - 2)
    else:
        tier = "large"
        required = math.ceil(total * 0.7)

    passed = success_count >= required

    return DataFetchCheckResult(
        passed=passed,
        total_count=total,
        success_count=success_count,
        failed_count=failed_count,
        required_count=required,
        tier=tier,
        failures=failures,
    )


_TIER_DESC = {
    "none": "无数据获取任务",
    "small": "1-3个API，至少1个成功",
    "medium": "4-6个API，允许最多2个失败",
    "large": "7+个API，至少70%成功",
}


def format_data_fetch_error(result: DataFetchCheckResult) -> str:
    """格式化 data_fetch 阈值检查结果为可读字符串。"""
    status = "PASS" if result.passed else "FAILED"
    lines = [
        f"数据获取诊断: {result.success_count}/{result.total_count} 成功"
        f" (要求 >={result.required_count}) [{status}]",
        f"阈值: {result.tier} ({_TIER_DESC.get(result.tier, '')})",
    ]
    if result.failures:
        lines.append("失败详情:")
        for f in result.failures:
            lines.append(
                f"  {f['task_id']} [{f['endpoint_id']}] "
                f"{f['error_type']}: {f['error_message']}"
            )
    return "\n".join(lines)


def _topological_layers(tasks: list[TaskItem]) -> list[list[TaskItem]]:
    """Organize tasks into layers by dependencies (Kahn's algorithm).

    Returns a list of layers, where each layer contains tasks that
    can be executed in parallel.
    """
    task_map = {t.task_id: t for t in tasks}
    in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
    adj: dict[str, list[str]] = {t.task_id: [] for t in tasks}

    for t in tasks:
        for dep in t.depends_on:
            if dep in adj:
                adj[dep].append(t.task_id)
                in_degree[t.task_id] += 1

    layers: list[list[TaskItem]] = []
    ready = [tid for tid, deg in in_degree.items() if deg == 0]

    while ready:
        layer = [task_map[tid] for tid in ready if tid in task_map]
        layers.append(layer)
        next_ready = []
        for tid in ready:
            for neighbor in adj.get(tid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_ready.append(neighbor)
        ready = next_ready

    return layers


async def _execute_single_task(
    task: TaskItem,
    context: dict[str, SkillOutput],
    ws_callback: Callable | None = None,
    allowed_skills: frozenset[str] | None = None,
) -> tuple[str, SkillOutput]:
    """Execute a single task, return (task_id, output)."""
    task_id = task.task_id
    skill_id = task.skill
    timeout = max(task.estimated_seconds * 3, 30)

    # Notify running
    if ws_callback:
        try:
            await ws_callback({
                "event": "task_update",
                "task_id": task_id,
                "status": "running",
                "message": f"正在执行 {task.name or skill_id}...",
            })
        except Exception:
            pass

    # 白名单检查
    if allowed_skills is not None and skill_id not in allowed_skills:
        output = SkillOutput(
            skill_id=skill_id,
            status="failed",
            output_type="json",
            error_message=f"技能 {skill_id} 不在当前员工范围内",
        )
        return task_id, output

    registry = SkillRegistry.get_instance()
    skill = registry.get_skill(skill_id)

    if skill is None:
        output = SkillOutput(
            skill_id=skill_id,
            status="failed",
            output_type="json",
            error_message=f"技能 {skill_id} 未注册",
        )
    else:
        inp = SkillInput(
            params=task.params,
            context_refs=task.depends_on,
        )
        output = await skill_executor(skill, inp, context, timeout_seconds=timeout)

    return task_id, output


async def execute_plan(
    tasks: list[TaskItem],
    ws_callback: Callable | None = None,
    allowed_skills: frozenset[str] | None = None,
) -> tuple[dict[str, str], dict[str, SkillOutput], bool]:
    """Execute an analysis plan.

    Returns:
        task_statuses: dict mapping task_id → "done"/"failed"
        execution_context: dict mapping task_id → SkillOutput
        needs_replan: whether dynamic re-planning is needed
    """
    import backend.skills.loader  # noqa: F401 — ensure all skills are registered

    layers = _topological_layers(tasks)
    task_statuses: dict[str, str] = {}
    execution_context: dict[str, SkillOutput] = {}
    needs_replan = False

    for layer in layers:
        # Execute tasks in batches of MAX_CONCURRENT
        for batch_start in range(0, len(layer), MAX_CONCURRENT):
            batch = layer[batch_start:batch_start + MAX_CONCURRENT]

            # Skip tasks whose dependencies failed
            runnable = []
            for task in batch:
                tracked_deps = [
                    dep for dep in task.depends_on if dep in task_statuses
                ]
                if task.type == "report_gen":
                    # Gate report_gen on data_fetch success threshold
                    df_check = check_data_fetch_threshold(
                        tasks, task_statuses, execution_context,
                    )
                    if not df_check.passed:
                        task_statuses[task.task_id] = "failed"
                        execution_context[task.task_id] = SkillOutput(
                            skill_id=task.skill,
                            status="failed",
                            output_type="json",
                            error_message=format_data_fetch_error(df_check),
                        )
                        logger.warning(
                            "Skipping report_gen %s: data_fetch threshold not met "
                            "(%d/%d, need >=%d)",
                            task.task_id, df_check.success_count,
                            df_check.total_count, df_check.required_count,
                        )
                        continue
                    # Threshold passed — lenient dep check: run if ANY dep or
                    # ANY global task succeeded (report skills scan full context)
                    deps_ok = any(
                        task_statuses.get(dep) == "done"
                        for dep in tracked_deps
                    ) if tracked_deps else True
                    if not deps_ok:
                        deps_ok = any(
                            v == "done" for v in task_statuses.values()
                        )
                else:
                    deps_ok = all(
                        task_statuses.get(dep) == "done"
                        for dep in tracked_deps
                    )
                if deps_ok:
                    runnable.append(task)
                else:
                    task_statuses[task.task_id] = "failed"
                    execution_context[task.task_id] = SkillOutput(
                        skill_id=task.skill,
                        status="failed",
                        output_type="json",
                        error_message="依赖任务失败",
                    )

            if not runnable:
                continue

            results = await asyncio.gather(
                *[_execute_single_task(t, execution_context, ws_callback, allowed_skills) for t in runnable],
                return_exceptions=True,
            )

            for i, result in enumerate(results):
                task = runnable[i]
                if isinstance(result, Exception):
                    task_statuses[task.task_id] = "failed"
                    execution_context[task.task_id] = SkillOutput(
                        skill_id=task.skill,
                        status="failed",
                        output_type="json",
                        error_message=str(result),
                    )
                else:
                    tid, output = result
                    status = "done" if output.status in ("success", "partial") else "failed"
                    task_statuses[tid] = status
                    execution_context[tid] = output

                    # Check dynamic re-plan triggers — only for truly empty results.
                    # Small row counts (2-7) are normal for aggregate/summary APIs.
                    if output.status == "success" and output.output_type == "dataframe":
                        row_count = output.metadata.get("rows", -1)
                        if row_count == 0:
                            needs_replan = True
                            logger.info(
                                "Task %s returned 0 rows — triggering re-plan",
                                tid,
                            )

                # Notify done/failed
                if ws_callback:
                    try:
                        await ws_callback({
                            "event": "task_update",
                            "task_id": task.task_id,
                            "status": task_statuses[task.task_id],
                            "message": f"{'完成' if task_statuses[task.task_id] == 'done' else '失败'}: {task.name or task.skill}",
                        })
                    except Exception:
                        pass

    return task_statuses, execution_context, needs_replan


async def execution_node(
    state: dict[str, Any],
    allowed_skills: frozenset[str] | None = None,
) -> dict[str, Any]:
    """LangGraph execution node — runs the analysis plan.

    Reads state["analysis_plan"]["tasks"], executes them, and updates state.
    allowed_skills: 员工技能白名单，由图工厂闭包注入。
    """
    import backend.skills.loader  # noqa: F401

    state["current_phase"] = "execution"
    plan = state.get("analysis_plan")
    if not plan:
        state["error"] = "No analysis plan to execute"
        return state

    raw_tasks = plan.get("tasks", [])
    tasks = []
    for t in raw_tasks:
        if isinstance(t, TaskItem):
            tasks.append(t)
        elif isinstance(t, dict):
            tasks.append(TaskItem(**t))
        else:
            continue

    if not tasks:
        state["error"] = "Analysis plan has no tasks"
        return state

    # Extract WebSocket callback from state (if provided)
    ws_callback = state.get("_ws_callback")

    task_statuses, execution_context, needs_replan = await execute_plan(
        tasks, ws_callback=ws_callback, allowed_skills=allowed_skills,
    )

    state["task_statuses"] = task_statuses
    state["execution_context"] = execution_context
    state["needs_replan"] = needs_replan

    # Determine next action
    all_done = all(v == "done" for v in task_statuses.values())
    if all_done and not needs_replan:
        state["messages"] = state.get("messages", [])
        state["messages"].append({
            "role": "assistant",
            "content": f"[Execution] 所有 {len(tasks)} 个任务执行完成。",
        })
        # Signal to graph: proceed to reflection
        state.setdefault("next_action", "reflection")
    elif needs_replan:
        state["messages"] = state.get("messages", [])
        state["messages"].append({
            "role": "assistant",
            "content": "[Execution] 数据量不足，需要重新规划。",
        })
    else:
        failed_count = sum(1 for v in task_statuses.values() if v == "failed")
        state["messages"] = state.get("messages", [])
        state["messages"].append({
            "role": "assistant",
            "content": f"[Execution] 完成 {len(tasks) - failed_count}/{len(tasks)} 个任务，{failed_count} 个失败。",
        })

    return state
