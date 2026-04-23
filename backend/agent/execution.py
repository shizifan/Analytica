"""Execution Node — executes tasks from AnalysisPlan with parallel support.

Features:
- Topological sort of task DAG
- Per-type concurrency (data_fetch=8, analysis=2, viz=4, report=1) via asyncio.Semaphore
- Per-type timeout profile (no longer blindly estimated_seconds*3)
- Retry with exponential backoff for transient errors (5xx / 429 / timeout)
- Data gate: viz/analysis tasks skip when all deps yield empty data
- Typed dependency policy: data_fetch=all, analysis=majority, viz=any
- Single task failure does not block others
- Dynamic re-planning on zero-row results
- WebSocket push support (optional callback)
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

import pandas as pd

from backend.models.schemas import TaskItem
from backend.skills.base import ErrorCategory, SkillInput, SkillOutput, skill_executor
from backend.skills.registry import SkillRegistry
from backend.tracing import make_span_emit

logger = logging.getLogger("analytica.execution")


def _summarize_skill_output(output: SkillOutput) -> dict[str, Any]:
    """Compact preview for the thinking stream's tool_call_end event.

    Must be small enough to post over WS hundreds of times per minute —
    no full DataFrames, no full text bodies, no LLM chain-of-thought.
    """
    preview: dict[str, Any] = {"output_type": getattr(output, "output_type", None)}
    data = getattr(output, "data", None)
    if data is None:
        return preview

    if isinstance(data, pd.DataFrame):
        preview["rows"] = int(len(data))
        preview["cols"] = int(len(data.columns))
        preview["columns"] = [str(c) for c in list(data.columns)[:6]]
    elif isinstance(data, (list, tuple)):
        preview["count"] = len(data)
        if data and isinstance(data[0], dict):
            preview["columns"] = list(data[0].keys())[:6]
    elif isinstance(data, dict):
        preview["keys"] = list(data.keys())[:8]
    elif isinstance(data, str):
        preview["char_count"] = len(data)
        preview["sample"] = data[:120]
    else:
        preview["kind"] = type(data).__name__
    return preview

# ── 并发 / 超时 / 重试配置 ─────────────────────────────────
#
# 不同类型任务的特性差异显著：data_fetch 是 IO 密集，可高并发；analysis 调用
# LLM，必须压低并发以防限流；visualization 轻量；report_gen 汇总，不并发。
# 旧的 MAX_CONCURRENT=3 一刀切导致 LLM 任务 429/超时频发，data_fetch 又跑不快。

# Per-type concurrency limits (Semaphore 在 execute_plan 第一次调用时惰性初始化，
# 避免模块 import 时绑定到错误的事件循环)。
_CONCURRENCY_LIMITS: dict[str, int] = {
    "data_fetch":    8,
    "analysis":      2,
    "visualization": 4,
    "report_gen":    1,
    "_default":      3,
}
_SEMAPHORES: dict[str, asyncio.Semaphore] = {}

# 兼容旧引用；语义已被 _CONCURRENCY_LIMITS 取代
MAX_CONCURRENT = 3

# Per-type timeout profile: (lower_bound, upper_bound, multiplier_on_estimated)
# resolved_timeout = clip(estimated_seconds * multiplier, lower, upper)
_TIMEOUT_PROFILE: dict[str, tuple[int, int, float]] = {
    "data_fetch":    (15, 45,  2.0),
    "analysis":      (60, 150, 2.5),   # LLM 调用通常 30-90s, 留足余量
    "visualization": (5,  20,  2.0),
    "report_gen":    (30, 120, 2.0),
    "_default":      (15, 90,  3.0),
}

# Retry policy: (max_attempts, retriable_error_categories)
_RETRY_POLICY: dict[str, tuple[int, frozenset[str]]] = {
    "data_fetch":    (3, frozenset({"TIMEOUT", "SERVER_ERROR", "RATE_LIMIT"})),
    "analysis":      (2, frozenset({"RATE_LIMIT", "TIMEOUT"})),
    "visualization": (1, frozenset()),
    "report_gen":    (2, frozenset({"TIMEOUT", "RATE_LIMIT"})),
    "_default":      (1, frozenset()),
}

# Dependency satisfaction policy by task type.
# "all"        — 所有依赖都必须 done（data_fetch/默认）
# "majority"   — 至少半数依赖 done（analysis，容忍部分 API 失败）
# "any"        — 任一依赖 done 即可（visualization，单源数据也可出图）
# "any_global" — 全局任一 done（report_gen，已有逻辑，下沉到此表以便统一）
_DEP_POLICY: dict[str, str] = {
    "data_fetch":    "all",
    "analysis":      "majority",
    "visualization": "any",
    "report_gen":    "any_global",
    "_default":      "all",
}


def _get_semaphore(task_type: str) -> asyncio.Semaphore:
    """Lazy-initialize semaphores on current event loop."""
    key = task_type if task_type in _CONCURRENCY_LIMITS else "_default"
    if key not in _SEMAPHORES:
        _SEMAPHORES[key] = asyncio.Semaphore(_CONCURRENCY_LIMITS[key])
    return _SEMAPHORES[key]


def _reset_semaphores() -> None:
    """Called at the start of each execute_plan to rebind semaphores to the
    current event loop. Without this, running the same process across multiple
    loops (e.g. pytest parametrized async tests) would reuse stale locks.
    """
    _SEMAPHORES.clear()


def _resolve_timeout(task: TaskItem) -> float:
    """Resolve per-task timeout. Prefers task.estimated_seconds when set,
    but clamps to per-type bounds."""
    profile = _TIMEOUT_PROFILE.get(task.type, _TIMEOUT_PROFILE["_default"])
    lo, hi, mult = profile
    est = task.estimated_seconds or lo
    return float(max(lo, min(est * mult, hi)))


def _classify_error_for_retry(error_message: str | None) -> str:
    """Minimal error classifier used for retry decisions.

    Returns one of: TIMEOUT / RATE_LIMIT / SERVER_ERROR / CLIENT_ERROR /
    AUTH / DEP_FAILED / UNKNOWN.

    NOTE: This is intentionally a string-matching classifier — batch 2 will
    replace it with exception-type classification at skill_executor level.
    """
    if not error_message:
        return "UNKNOWN"
    text = error_message.lower()
    if "timeout" in text or "超时" in text or "timed out" in text:
        return "TIMEOUT"
    if "rate" in text and "limit" in text:
        return "RATE_LIMIT"
    if "429" in text:
        return "RATE_LIMIT"
    if "401" in text or "认证失败" in text or "unauthorized" in text:
        return "AUTH"
    if any(c in text for c in ("500", "502", "503", "504")):
        return "SERVER_ERROR"
    if "服务端错误" in text:
        return "SERVER_ERROR"
    if any(c in text for c in ("400", "404")):
        return "CLIENT_ERROR"
    if "客户端错误" in text:
        return "CLIENT_ERROR"
    if "依赖任务失败" in text or "dependency" in text:
        return "DEP_FAILED"
    return "UNKNOWN"


def _deps_have_data(
    task: TaskItem,
    context: dict[str, SkillOutput],
) -> tuple[bool, str]:
    """Check whether upstream deps contain usable data for this task.

    Only enforced for analysis / visualization — these consume data and
    will produce garbage (or crash) when handed empty frames.

    Returns (has_data, reason). reason is empty when has_data=True.
    """
    if task.type not in ("analysis", "visualization"):
        return True, ""

    if not task.depends_on:
        # No deps means the skill itself fetches/produces data (or uses full context)
        return True, ""

    checked = 0
    for dep in task.depends_on:
        out = context.get(dep)
        if out is None:
            continue
        checked += 1
        if out.status not in ("success", "partial"):
            continue
        data = out.data
        if isinstance(data, pd.DataFrame) and not data.empty:
            return True, ""
        if isinstance(data, dict) and data:
            # analysis output dict (summary_stats / narrative / growth_rates)
            return True, ""
        if isinstance(data, (list, tuple)) and data:
            return True, ""
        if isinstance(data, str) and data.strip():
            return True, ""

    if checked == 0:
        # None of the declared deps are in context yet — treat as OK (topological
        # order should normally prevent this; defer to the regular dep check).
        return True, ""
    return False, f"所有 {checked} 个上游依赖均为空数据"


def _deps_satisfied(
    task: TaskItem,
    task_statuses: dict[str, str],
) -> bool:
    """Apply per-type dependency policy."""
    tracked = [d for d in task.depends_on if d in task_statuses]
    policy = _DEP_POLICY.get(task.type, _DEP_POLICY["_default"])

    if policy == "any_global":
        if tracked:
            if any(task_statuses.get(d) == "done" for d in tracked):
                return True
        return any(v == "done" for v in task_statuses.values())

    if not tracked:
        return True

    done = sum(1 for d in tracked if task_statuses.get(d) == "done")

    if policy == "all":
        return done == len(tracked)
    if policy == "majority":
        return done * 2 >= len(tracked) and done >= 1
    if policy == "any":
        return done >= 1
    return done == len(tracked)  # fail-safe


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
    """Execute a single task with concurrency limit, timeout, retry, and data gate.

    Returns (task_id, output). Output.status may be one of:
      - "success" / "partial"  — skill succeeded
      - "failed"               — skill failed (after retries exhausted)
      - "skipped"              — pre-flight check determined task cannot run
    """
    task_id = task.task_id
    skill_id = task.skill

    # ── Pre-flight 1: skill whitelist ─────────────────────
    if allowed_skills is not None and skill_id not in allowed_skills:
        return task_id, SkillOutput(
            skill_id=skill_id, status="failed", output_type="json",
            error_message=f"技能 {skill_id} 不在当前员工范围内",
        )

    # ── Pre-flight 2: skill registration ──────────────────
    registry = SkillRegistry.get_instance()
    skill = registry.get_skill(skill_id)
    if skill is None:
        return task_id, SkillOutput(
            skill_id=skill_id, status="failed", output_type="json",
            error_message=f"技能 {skill_id} 未注册",
        )

    # ── Pre-flight 3: data gate (viz/analysis only) ────────
    has_data, reason = _deps_have_data(task, context)
    if not has_data:
        logger.info("Task %s skipped: %s", task_id, reason)
        if ws_callback:
            try:
                await ws_callback({
                    "event": "task_update",
                    "task_id": task_id,
                    "status": "skipped",
                    "message": f"跳过 {task.name or skill_id}: {reason}",
                })
            except Exception:
                pass
        return task_id, SkillOutput(
            skill_id=skill_id, status="skipped", output_type="json",
            error_message=reason,
            metadata={"skip_reason": "EMPTY_DEPS"},
        )

    # ── Notify running ────────────────────────────────────
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

    # ── Semaphore-bounded execution with retry ────────────
    timeout = _resolve_timeout(task)
    max_attempts, retriable = _RETRY_POLICY.get(
        task.type, _RETRY_POLICY["_default"],
    )
    sem = _get_semaphore(task.type)

    span_emit = make_span_emit(task_id, ws_callback)

    output: SkillOutput | None = None
    for attempt in range(1, max_attempts + 1):
        inp = SkillInput(
            params={**task.params, "__task_id__": task_id},
            context_refs=task.depends_on,
            span_emit=span_emit,
        )
        # ── tool_call_start (Phase 2) ──────────────────────
        call_id = f"{task_id}#{attempt}"
        if ws_callback:
            try:
                # Keep args payload compact — skip huge data context refs.
                args_preview = {
                    k: v for k, v in task.params.items()
                    if not isinstance(v, (list, dict)) or len(repr(v)) < 500
                }
                await ws_callback({
                    "event": "tool_call_start",
                    "call_id": call_id,
                    "task_id": task_id,
                    "skill_id": skill_id,
                    "attempt": attempt,
                    "args": args_preview,
                })
            except Exception:
                pass

        async with sem:
            output = await skill_executor(skill, inp, context, timeout_seconds=timeout)

        output.attempt_count = attempt

        # ── tool_call_end (Phase 2 + 3.5 preview) ──────────
        if ws_callback:
            try:
                preview = _summarize_skill_output(output)
                await ws_callback({
                    "event": "tool_call_end",
                    "call_id": call_id,
                    "task_id": task_id,
                    "skill_id": skill_id,
                    "status": output.status,
                    "error": output.error_message,
                    "error_category": output.error_category,
                    "preview": preview,
                })
            except Exception:
                pass

        if output.status in ("success", "partial"):
            break

        # Prefer the exception-based classification from skill_executor; fall
        # back to string matching for errors bubbled up without a category
        # (e.g. skills that emit self._fail("...") with no exception context).
        category = output.error_category or _classify_error_for_retry(
            output.error_message,
        )
        output.error_category = category

        if attempt >= max_attempts or category not in retriable:
            break

        # Exponential backoff: 1s, 2s, 4s
        backoff = 2 ** (attempt - 1)
        logger.info(
            "Task %s attempt %d/%d failed (%s: %s) — retrying in %ds",
            task_id, attempt, max_attempts, category,
            (output.error_message or "")[:80], backoff,
        )
        await asyncio.sleep(backoff)

    return task_id, output  # type: ignore[return-value]


async def execute_plan(
    tasks: list[TaskItem],
    ws_callback: Callable | None = None,
    allowed_skills: frozenset[str] | None = None,
    report_dir: Path | str | None = None,
    persist_snapshot: Callable[[dict[str, str]], Any] | None = None,
) -> tuple[dict[str, str], dict[str, SkillOutput], bool]:
    """Execute an analysis plan.

    Args:
        tasks: topologically ordered TaskItem list
        ws_callback: optional websocket notifier
        allowed_skills: per-employee skill whitelist
        report_dir: if provided, dump execution_report.json here after execution
        persist_snapshot: optional async callback invoked after each layer
            with a copy of the current task_statuses. Used by the graph
            node to incrementally persist progress so a user who switches
            sessions mid-execution can hydrate real progress on return.
            Failures are logged and ignored — never block execution.

    Returns:
        task_statuses: dict mapping task_id → "done"/"failed"/"skipped"
        execution_context: dict mapping task_id → SkillOutput
        needs_replan: whether dynamic re-planning is needed
    """
    import backend.skills.loader  # noqa: F401 — ensure all skills are registered

    _reset_semaphores()  # rebind to current event loop

    layers = _topological_layers(tasks)
    # Global task order (template declaration / topological) — threaded into
    # report_gen tasks so _content_collector iterates items in the same
    # sequence rather than in lexicographic dict order.
    global_task_order = [t.task_id for t in tasks]

    task_statuses: dict[str, str] = {}
    execution_context: dict[str, SkillOutput] = {}
    needs_replan = False

    for layer_idx, layer in enumerate(layers):
        runnable: list[TaskItem] = []

        # ── Per-task pre-flight: dep policy + report_gen threshold ──
        for task in layer:
            # report_gen retains the data_fetch threshold gate (stricter than dep policy)
            if task.type == "report_gen":
                df_check = check_data_fetch_threshold(
                    tasks, task_statuses, execution_context,
                )
                if not df_check.passed:
                    task_statuses[task.task_id] = "failed"
                    execution_context[task.task_id] = SkillOutput(
                        skill_id=task.skill, status="failed", output_type="json",
                        error_message=format_data_fetch_error(df_check),
                    )
                    logger.warning(
                        "Skipping report_gen %s: data_fetch threshold not met "
                        "(%d/%d, need >=%d)",
                        task.task_id, df_check.success_count,
                        df_check.total_count, df_check.required_count,
                    )
                    continue

            if _deps_satisfied(task, task_statuses):
                # Inject global task order into report_gen params so the
                # content collector can iterate in template-declaration order.
                if task.type == "report_gen" and "_task_order" not in task.params:
                    task.params = {**task.params, "_task_order": global_task_order}
                runnable.append(task)
            else:
                task_statuses[task.task_id] = "failed"
                execution_context[task.task_id] = SkillOutput(
                    skill_id=task.skill, status="failed", output_type="json",
                    error_message="依赖任务失败",
                    metadata={"error_category": "DEP_FAILED"},
                )
                if ws_callback:
                    try:
                        await ws_callback({
                            "event": "task_update",
                            "task_id": task.task_id,
                            "status": "failed",
                            "message": f"跳过：{task.name or task.skill}（上游任务失败）",
                        })
                    except Exception:
                        pass

        if not runnable:
            continue

        # ── Execute full layer in parallel; semaphores cap per-type concurrency ──
        layer_start = time.monotonic()
        results = await asyncio.gather(
            *[
                _execute_single_task(t, execution_context, ws_callback, allowed_skills)
                for t in runnable
            ],
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            task = runnable[i]
            if isinstance(result, Exception):
                task_statuses[task.task_id] = "failed"
                execution_context[task.task_id] = SkillOutput(
                    skill_id=task.skill, status="failed", output_type="json",
                    error_message=str(result),
                )
            else:
                tid, output = result
                # Preserve partial / skipped in the bucket so downstream
                # content_collector / report skills can filter on it.
                if output.status in ("success", "partial"):
                    task_statuses[tid] = "done"
                elif output.status == "skipped":
                    task_statuses[tid] = "skipped"
                else:
                    task_statuses[tid] = "failed"
                execution_context[tid] = output

                # Re-plan trigger — only for truly empty results.
                if (output.status == "success"
                        and output.output_type == "dataframe"):
                    row_count = output.metadata.get("rows", -1)
                    if row_count == 0:
                        needs_replan = True
                        logger.info(
                            "Task %s returned 0 rows — triggering re-plan", tid,
                        )

            # WebSocket notify
            if ws_callback:
                try:
                    st = task_statuses[task.task_id]
                    label = {"done": "完成", "failed": "失败", "skipped": "跳过"}.get(st, st)
                    await ws_callback({
                        "event": "task_update",
                        "task_id": task.task_id,
                        "status": st,
                        "message": f"{label}: {task.name or task.skill}",
                    })
                except Exception:
                    pass

        # ── Layer summary log ──────────────────────────────────
        elapsed = time.monotonic() - layer_start
        done = sum(1 for t in runnable if task_statuses.get(t.task_id) == "done")
        failed = sum(1 for t in runnable if task_statuses.get(t.task_id) == "failed")
        skipped = sum(1 for t in runnable if task_statuses.get(t.task_id) == "skipped")
        err_counter: Counter[str] = Counter()
        retried = 0
        for t in runnable:
            out = execution_context.get(t.task_id)
            if out and out.error_category:
                err_counter[out.error_category] += 1
            if out and out.attempt_count and out.attempt_count > 1:
                retried += 1
        err_frag = f" errors={dict(err_counter)}" if err_counter else ""
        retry_frag = f" retried={retried}" if retried else ""
        logger.info(
            "[Layer %d] tasks=%d elapsed=%.2fs done=%d failed=%d skipped=%d%s%s",
            layer_idx, len(runnable), elapsed, done, failed, skipped,
            retry_frag, err_frag,
        )

        # ── P1: snapshot task_statuses after each layer so a user who
        #    switches sessions mid-execution can see real progress on return.
        if persist_snapshot is not None:
            try:
                await persist_snapshot(dict(task_statuses))
            except Exception:
                logger.exception("persist_snapshot callback failed; continuing")

    # ── Dump execution_report.json when report_dir is provided ──
    if report_dir is not None:
        try:
            _dump_execution_report(tasks, task_statuses, execution_context, Path(report_dir))
        except Exception as e:  # never let the dump break the pipeline
            logger.warning("Failed to dump execution report: %s", e)

    return task_statuses, execution_context, needs_replan


# ── Execution report helpers ─────────────────────────────────

def build_execution_report(
    tasks: list[TaskItem],
    task_statuses: dict[str, str],
    execution_context: dict[str, SkillOutput],
) -> dict[str, Any]:
    """Build a structured execution report for observability / regression diffs.

    Structure:
        {
          "summary": {total, done, failed, skipped, total_elapsed_seconds,
                      errors_by_category, retried_count, llm_tokens_total},
          "tasks":   [ per-task record … ]
        }
    """
    records: list[dict[str, Any]] = []
    errors_by_category: Counter[str] = Counter()
    retried = 0
    llm_prompt = 0
    llm_completion = 0
    total_elapsed = 0.0

    for t in tasks:
        out = execution_context.get(t.task_id)
        status = task_statuses.get(t.task_id, "unknown")
        elapsed = round(out.elapsed_seconds, 3) if out else 0.0
        attempt = out.attempt_count if out else 1
        rec = {
            "task_id": t.task_id,
            "type": t.type,
            "skill": t.skill,
            "name": t.name or "",
            "status": status,
            "elapsed_seconds": elapsed,
            "attempt_count": attempt,
            "error_category": out.error_category if out else None,
            "error_message": (
                (out.error_message or "")[:500] if out and out.error_message else None
            ),
            "rows": (out.metadata.get("rows") if out else None),
            "skip_reason": (out.metadata.get("skip_reason") if out else None),
            "llm_tokens": (out.llm_tokens if out else {}),
        }
        records.append(rec)
        if out:
            total_elapsed += out.elapsed_seconds
            if out.error_category:
                errors_by_category[out.error_category] += 1
            if attempt > 1:
                retried += 1
            toks = out.llm_tokens or {}
            llm_prompt += int(toks.get("prompt", 0) or 0)
            llm_completion += int(toks.get("completion", 0) or 0)

    status_counts = Counter(task_statuses.values())
    summary = {
        "total": len(tasks),
        "done": status_counts.get("done", 0),
        "failed": status_counts.get("failed", 0),
        "skipped": status_counts.get("skipped", 0),
        "total_elapsed_seconds": round(total_elapsed, 3),
        "retried_count": retried,
        "errors_by_category": dict(errors_by_category),
        "llm_tokens_total": {"prompt": llm_prompt, "completion": llm_completion},
    }
    return {"summary": summary, "tasks": records}


def _dump_execution_report(
    tasks: list[TaskItem],
    task_statuses: dict[str, str],
    execution_context: dict[str, SkillOutput],
    report_dir: Path,
) -> Path:
    """Persist the execution report to ``report_dir / execution_report.json``."""
    report_dir.mkdir(parents=True, exist_ok=True)
    report = build_execution_report(tasks, task_statuses, execution_context)
    path = report_dir / "execution_report.json"
    path.write_text(
        _json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Execution report saved: %s", path)
    return path


# ── 结果格式化 ───────────────────────────────────────────────

MAX_TABLE_ROWS = 20


async def _persist_file_artifacts(
    session_id: str,
    tasks: list[TaskItem],
    execution_context: dict[str, SkillOutput],
    task_statuses: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Phase 5 — write every successful file-output task to REPORTS_DIR
    and insert a `report_artifacts` row. Returns a mapping
    ``{task_id: artifact_row}`` for the payload builder to embed as
    ``data.artifact_id`` on the frontend card.
    """
    from backend.database import get_session_factory
    from backend.memory import artifact_store

    artifacts: dict[str, dict[str, Any]] = {}
    factory = get_session_factory()

    for task in tasks:
        tid = task.task_id
        if task_statuses.get(tid) != "done":
            continue
        output = execution_context.get(tid)
        if output is None or output.output_type != "file":
            continue
        if output.status not in ("success", "partial"):
            continue

        meta = output.metadata or {}
        fmt = str(meta.get("format", "file")).lower()
        title = meta.get("title") or task.name or tid
        try:
            async with factory() as db:
                row = await artifact_store.persist_artifact(
                    db,
                    session_id=session_id,
                    task_id=tid,
                    skill_id=task.skill,
                    fmt=fmt,
                    title=title,
                    content=output.data,
                    meta={
                        k: v for k, v in meta.items()
                        if k not in ("format", "title", "path")
                    },
                )
        except Exception:
            logger.exception("persist_artifact failed for task %s", tid)
            row = None

        if row:
            artifacts[tid] = row

            # Phase 5.7 — for HTML reports, save the upstream context
            # alongside so the user can click "生成 DOCX / PPTX" later
            # and we can re-run the rendering skill without a full
            # graph execution.
            if (row.get("format") == "html"
                    and (task.skill or "").startswith("skill_report_")):
                try:
                    sub_ctx = _collect_report_context(
                        task, tasks, execution_context,
                    )
                    from backend.memory import artifact_store
                    artifact_store.write_conversion_context(
                        row["id"],
                        {
                            "params": dict(task.params or {}),
                            "context": sub_ctx,
                            "session_id": session_id,
                            "task_order": [t.task_id for t in tasks],
                        },
                    )
                except Exception:
                    logger.exception(
                        "failed to persist conversion ctx for %s", tid,
                    )

    return artifacts


def _collect_report_context(
    report_task: TaskItem,
    all_tasks: list[TaskItem],
    execution_context: dict[str, SkillOutput],
) -> dict[str, Any]:
    """Walk transitively from the report task through `depends_on` and
    build a minimal context dict for later skill re-invocation."""
    needed: set[str] = set()
    frontier: list[str] = list(report_task.depends_on or [])
    by_id = {t.task_id: t for t in all_tasks}
    while frontier:
        tid = frontier.pop()
        if tid in needed:
            continue
        needed.add(tid)
        nxt = by_id.get(tid)
        if nxt and nxt.depends_on:
            frontier.extend(nxt.depends_on)
    return {
        tid: execution_context[tid]
        for tid in needed
        if tid in execution_context
    }


def _build_task_results_payload(
    tasks: list[TaskItem],
    execution_context: dict[str, SkillOutput],
    task_statuses: dict[str, str],
    artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Phase 3.7 — structured projection of successful tasks for the V2
    Result Card renderer. Returns a dict with `tasks: [...]` matching the
    `TaskResult` contract consumed by the frontend.

    Each entry is ≤ a few KB — large DataFrames are full-row (for CSV
    download) but deep-object previews are capped.
    """
    import pandas as pd

    out_tasks: list[dict[str, Any]] = []

    for task in tasks:
        tid = task.task_id
        if task_statuses.get(tid) != "done":
            continue

        output = execution_context.get(tid)
        if output is None or output.status not in ("success", "partial"):
            continue

        entry: dict[str, Any] = {
            "task_id": tid,
            "name": task.name or task.skill,
            "skill": task.skill,
            "type": task.type,
            "depends_on": list(task.depends_on or []),
            "output_type": "unknown",
            "data": None,
        }

        # Optional metadata
        ep_id = task.params.get("endpoint_id") if task.params else None
        if ep_id:
            entry["source_api"] = ep_id
        duration_ms = getattr(output, "duration_ms", None)
        if duration_ms:
            entry["duration_ms"] = int(duration_ms)

        data = output.data
        try:
            if output.output_type == "dataframe" and isinstance(data, pd.DataFrame):
                entry["output_type"] = "table"
                # Keep full data — CSV download needs every row.
                columns = [str(c) for c in data.columns]
                # Replace NaN/NaT with None so JSON serialisation stays
                # honest (otherwise floats become NaN literals which json
                # can't emit and the frontend would show "NaN").
                rows: list[list[Any]] = []
                for record in data.itertuples(index=False, name=None):
                    row: list[Any] = []
                    for value in record:
                        if value is None:
                            row.append(None)
                        elif isinstance(value, float) and (value != value):  # NaN
                            row.append(None)
                        elif hasattr(pd, "isna") and pd.isna(value):
                            row.append(None)
                        else:
                            row.append(value)
                    rows.append(row)
                entry["data"] = {
                    "columns": columns,
                    "rows": rows,
                    "total_rows": int(len(data)),
                }

            elif output.output_type == "chart" and isinstance(data, dict):
                entry["output_type"] = "chart"
                entry["data"] = {"option": data}

            elif output.output_type == "text" and data:
                entry["output_type"] = "text"
                entry["data"] = {"text": str(data)}

            elif output.output_type == "json" and isinstance(data, dict):
                narrative = data.get("narrative") or data.get("description")
                if narrative:
                    entry["output_type"] = "text"
                    entry["data"] = {"text": str(narrative)}
                else:
                    entry["output_type"] = "json"
                    entry["data"] = {"object": data}

            elif output.output_type == "file":
                entry["output_type"] = "file"
                fmt = (output.metadata or {}).get("format", "file")
                artifact = (artifacts or {}).get(tid)
                entry["data"] = {
                    "format": str(fmt).upper(),
                    "artifact_id": artifact["id"] if artifact else None,
                    "title": (
                        (output.metadata or {}).get("title")
                        or task.name
                    ),
                    "size_bytes": artifact.get("size_bytes") if artifact else None,
                }
            else:
                continue  # Unknown shape; don't surface to UI
        except Exception:
            logger.exception("task_results payload failed for %s", tid)
            continue

        out_tasks.append(entry)

    # ── Phase 5.8: report pipelines hide intermediates ─────────
    # When the pipeline produced a file (HTML report), everything the
    # user asked for lives IN that file. Tables / charts / analysis
    # text rendered alongside would just be noise. Keep only the file
    # entries — the user can preview or download to see the full
    # contents, and the PlanTab / Thinking stream still expose the
    # intermediate steps for anyone curious.
    file_entries = [e for e in out_tasks if e["output_type"] == "file"]
    if file_entries:
        return {"tasks": file_entries, "pipeline": "report"}

    return {"tasks": out_tasks}


def _format_execution_results(
    tasks: list[TaskItem],
    execution_context: dict[str, SkillOutput],
    task_statuses: dict[str, str],
) -> list[str]:
    """将 execution_context 中的成功结果格式化为 markdown 内容块。

    返回内容块列表，每个块对应一个成功任务的格式化输出。
    - dataframe → markdown 表格（截断到 MAX_TABLE_ROWS 行）
    - chart     → ```echarts JSON``` 代码块（前端检测并用 EChartsViewer 渲染）
    - text      → 直接文本
    - json      → 提取 narrative 字段；若无则格式化为 JSON 代码块
    - file      → 提示已生成文件
    """
    import pandas as pd

    parts: list[str] = []

    for task in tasks:
        tid = task.task_id
        if task_statuses.get(tid) != "done":
            continue

        output = execution_context.get(tid)
        if output is None or output.status not in ("success", "partial"):
            continue

        task_name = task.name or task.skill

        try:
            if output.output_type == "dataframe" and output.data is not None:
                df = output.data
                if isinstance(df, pd.DataFrame):
                    row_count = len(df)
                    if row_count == 0:
                        parts.append(f"**{task_name}**\n\n*（查询结果为空）*")
                    else:
                        display_df = df.head(MAX_TABLE_ROWS) if row_count > MAX_TABLE_ROWS else df
                        table_md = display_df.to_markdown(index=False)
                        if row_count > MAX_TABLE_ROWS:
                            table_md += f"\n\n*（仅展示前 {MAX_TABLE_ROWS} 行，共 {row_count} 行）*"
                        parts.append(f"**{task_name}**\n\n{table_md}")

            elif output.output_type == "chart" and output.data is not None:
                chart_json = _json.dumps(output.data, ensure_ascii=False)
                parts.append(f"**{task_name}**\n\n```echarts\n{chart_json}\n```")

            elif output.output_type == "text" and output.data:
                parts.append(f"**{task_name}**\n\n{output.data}")

            elif output.output_type == "json" and isinstance(output.data, dict):
                narrative = output.data.get("narrative", "")
                if narrative:
                    parts.append(f"**{task_name}**\n\n{narrative}")
                else:
                    formatted = _json.dumps(output.data, ensure_ascii=False, indent=2)
                    parts.append(f"**{task_name}**\n\n```json\n{formatted}\n```")

            elif output.output_type == "file":
                fmt = output.metadata.get("format", "file").upper()
                parts.append(f"**{task_name}**\n\n*已生成 {fmt} 报告。*")

        except Exception as exc:
            logger.warning("格式化任务 %s 结果失败: %s", tid, exc)
            parts.append(f"**{task_name}**\n\n*（结果格式化失败）*")

    return parts


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

    # Phase 3.5: ws_callback now flows through contextvars instead of
    # the state dict — survives LangGraph state merging and doesn't
    # pollute state_json serialisation.
    from backend.agent.ws_ctx import get_ws_callback
    ws_callback = get_ws_callback() or state.get("_ws_callback")  # back-compat

    # P1: per-layer snapshot so switching sessions mid-execution doesn't
    # leave hydration reading stale DB state. Each layer completion writes
    # a copy of the current task_statuses into sessions.state_json.
    session_id = state.get("session_id") or ""

    async def _persist_layer_snapshot(statuses: dict[str, str]) -> None:
        if not session_id:
            return
        from backend.database import get_session_factory
        from backend.memory.store import MemoryStore
        snapshot = {**state, "task_statuses": dict(statuses), "current_phase": "execution"}
        try:
            safe = _json.loads(_json.dumps(snapshot, ensure_ascii=False, default=str))
        except Exception:
            logger.exception("snapshot serialization failed; skipping persist")
            return
        factory = get_session_factory()
        try:
            async with factory() as db:
                await MemoryStore(db).save_session_state(session_id, safe)
        except Exception:
            logger.exception("per-layer state persist failed for %s", session_id)

    task_statuses, execution_context, needs_replan = await execute_plan(
        tasks,
        ws_callback=ws_callback,
        allowed_skills=allowed_skills,
        persist_snapshot=_persist_layer_snapshot if session_id else None,
    )

    state["task_statuses"] = task_statuses
    state["execution_context"] = execution_context

    _MAX_REPLAN = 1
    replan_count = state.get("replan_count", 0)
    if needs_replan:
        if replan_count >= _MAX_REPLAN:
            needs_replan = False
            state["error"] = "数据持续为空，已达重新规划上限，终止执行。"
            logger.warning(
                "Replan limit (%d) reached for session %s; aborting replan cycle",
                _MAX_REPLAN, session_id,
            )
        else:
            state["replan_count"] = replan_count + 1

    state["needs_replan"] = needs_replan

    # Determine next action — skipped tasks are terminal but not failures
    terminal_ok = {"done", "skipped"}
    all_done = all(v in terminal_ok for v in task_statuses.values())
    if all_done and not needs_replan:
        # Phase 5 — persist any file outputs to disk + report_artifacts
        # table BEFORE building the payload, so the structured entries
        # carry the DB artifact id the frontend download buttons use.
        artifacts = await _persist_file_artifacts(
            state.get("session_id", ""),
            tasks, execution_context, task_statuses,
        )
        # Format and append execution result content
        result_parts = _format_execution_results(tasks, execution_context, task_statuses)
        structured = _build_task_results_payload(
            tasks, execution_context, task_statuses, artifacts=artifacts,
        )
        is_report = structured.get("pipeline") == "report"
        state["messages"] = state.get("messages", [])
        if result_parts:
            if is_report:
                # Phase 5.8 — for report pipelines, the chat stream just
                # announces completion. All the numbers / charts /
                # narrative live inside the rendered report file, so
                # echoing them in Markdown would be redundant noise.
                file_count = len(structured.get("tasks", []))
                total = len(tasks)
                done_count = sum(1 for v in task_statuses.values() if v == "done")
                content = (
                    f"已生成深度分析报告（{file_count} 份文件 · "
                    f"{done_count}/{total} 个子任务）。"
                    f"可在下方预览 / 下载，或按需导出其它格式。"
                )
            else:
                content = "\n\n---\n\n".join(result_parts)
            state["messages"].append({
                "role": "assistant",
                "type": "task_results",
                "content": content,
                "payload": structured,
            })
        else:
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
        skipped_count = sum(1 for v in task_statuses.values() if v == "skipped")
        done_count = sum(1 for v in task_statuses.values() if v == "done")
        # 收集失败任务的错误信息，方便排查
        error_details = []
        for t in tasks:
            if task_statuses.get(t.task_id) == "failed":
                ctx = execution_context.get(t.task_id)
                err_msg = ctx.error_message if ctx and ctx.error_message else "未知错误"
                error_details.append(f"  - {t.name or t.task_id} ({t.skill}): {err_msg}")
        detail_text = "\n".join(error_details) if error_details else ""
        state["messages"] = state.get("messages", [])
        skipped_suffix = f"，{skipped_count} 个跳过" if skipped_count else ""
        state["messages"].append({
            "role": "assistant",
            "content": (
                f"[Execution] 完成 {done_count}/{len(tasks)} 个任务，"
                f"{failed_count} 个失败{skipped_suffix}。\n{detail_text}"
            ).strip(),
        })
        # Still format and send results from successful tasks
        result_parts = _format_execution_results(tasks, execution_context, task_statuses)
        if result_parts:
            state["messages"].append({
                "role": "assistant",
                "content": "\n\n---\n\n".join(result_parts),
            })

    return state
