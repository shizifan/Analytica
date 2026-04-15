"""PlanningEngine — 规划层核心。

接收感知层输出的 StructuredIntent，调用 LLM 生成 AnalysisPlan，
验证技能/端点合法性，提供 Markdown 展示和版本管理。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from backend.exceptions import PlanningError
from backend.models.schemas import AnalysisPlan, TaskItem
from backend.agent.skills import VALID_SKILL_IDS, get_skills_description
from backend.agent.endpoints import (
    ENDPOINT_REGISTRY,
    VALID_ENDPOINT_IDS,
    get_endpoints_description,
    resolve_endpoint_id,
)

logger = logging.getLogger("analytica.planning")

# ── Task count limits per complexity ─────────────────────────

TASK_COUNT_LIMITS = {
    "simple_table": (2, 3),
    "chart_text": (3, 5),
    "full_report": (5, 8),
}

# ── Planning LLM Prompt ──────────────────────────────────────

PLANNING_PROMPT = """你是一个数据分析规划专家。根据用户的分析意图，制定一份分析执行方案。

【分析意图】
{intent_json}

【可用技能清单】
{skills_description}

【可用数据端点】
{endpoints_description}

{template_hint}

【任务数量要求】
- simple_table: 2-3 个任务
- chart_text: 3-5 个任务
- full_report: 5-8 个任务
当前复杂度: {complexity}

【重要约束】
1. 所有任务的 skill 字段必须从上方「可用技能清单」中选取
2. 所有 data_fetch 类任务的 params.endpoint_id 必须从上方「可用数据端点」中选取
3. getMarketTrendChart（M12）的 businessSegment 为【必填】参数
4. depends_on 引用的 task_id 必须在 tasks 列表中存在，不能有循环依赖
5. 集装箱有 TEU 和吨双单位，不可直接加总
6. task_id 按 T001, T002, ... 编号
7. 集装箱 TEU 专项查询请优先使用 getContainerThroughput（M04），而非市场域端点
8. 生产域与市场域的"吞吐量"口径不同：生产视角用 M01-M09，市场视角用 M10-M15

【多数据源分析指引】
- 归因分析(attribution)：查找变化原因时，应获取重点企业贡献(M14)或板块占比(M15)等辅助数据
- 同比/环比对比：需要多期数据时，考虑趋势端点(M03/M12)配合区域对比(M13)或板块对比(M02)
- 跨域分析：涉及多个领域（如"资产+投资"）时，应分别从各域获取数据（如 M21-M24 + M25-M27）
- 投资进度分析：月度执行节奏用 M26，年度完成率/计划汇总用 M25，偏差分析建议两者配合
{report_hint}

【输出格式】（严格 JSON，无 <think> 块，无 markdown 包裹）
{{
  "title": "方案标题（简洁中文）",
  "analysis_goal": "分析目标描述",
  "estimated_duration": <总预计秒数>,
  "tasks": [
    {{
      "task_id": "T001",
      "type": "data_fetch | search | analysis | visualization | report_gen",
      "name": "任务名称",
      "description": "对用户友好的描述",
      "depends_on": [],
      "skill": "技能ID",
      "params": {{"endpoint_id": "端点ID", ...}},
      "estimated_seconds": 10
    }}
  ],
  "report_structure": null
}}

如果是 full_report 场景，report_structure 应包含报告章节结构：
{{"sections": ["封面", "目录", "数据概览", ...]}}
"""


def _strip_think_tags(text: str) -> str:
    """Remove Qwen3's <think>...</think> reasoning blocks."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines)
    return text.strip()


def _clean_llm_output(raw: str) -> str:
    """Clean LLM output: strip think tags, markdown fences, non-JSON prefix."""
    cleaned = _strip_think_tags(raw)
    cleaned = _strip_markdown_fences(cleaned)
    # Try to find JSON object in the text
    idx = cleaned.find("{")
    if idx > 0:
        cleaned = cleaned[idx:]
    return cleaned.strip()


def parse_planning_llm_output(raw: str) -> dict:
    """Parse and clean planning LLM output into a dict.

    Raises PlanningError if JSON parsing fails.
    """
    cleaned = _clean_llm_output(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise PlanningError(f"规划 LLM 输出非法 JSON: {e}\n原文前200字: {cleaned[:200]}")


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    """Detect cycles in a directed graph using DFS."""
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True
        rec_stack.discard(node)
        return False

    return any(dfs(n) for n in graph if n not in visited)


def _break_cycles(tasks: list[TaskItem]) -> list[TaskItem]:
    """Detect and break circular dependencies by removing back edges."""
    graph = {t.task_id: list(t.depends_on) for t in tasks}
    if not _has_cycle(graph):
        return tasks

    logger.warning("Detected circular dependency in task graph, breaking cycles")
    task_map = {t.task_id: t for t in tasks}
    # Topological approach: remove edges that cause cycles
    visited: set[str] = set()
    in_progress: set[str] = set()

    def dfs_break(node: str) -> None:
        visited.add(node)
        in_progress.add(node)
        task = task_map.get(node)
        if task:
            new_deps = []
            for dep in task.depends_on:
                if dep in in_progress:
                    logger.warning("Breaking cycle: removing %s -> %s edge", node, dep)
                    continue
                new_deps.append(dep)
                if dep not in visited:
                    dfs_break(dep)
            task.depends_on = new_deps
        in_progress.discard(node)

    for tid in graph:
        if tid not in visited:
            dfs_break(tid)

    return tasks


class PlanningEngine:
    """Core planning engine for the planning layer."""

    def __init__(
        self,
        llm: Any = None,
        llm_timeout: float = 120.0,
        max_retries: int = 3,
    ):
        self.llm = llm
        self.llm_timeout = llm_timeout
        self.max_retries = max_retries

    async def generate_plan(
        self,
        intent: dict[str, Any],
        available_skills: dict[str, Any] | None = None,
        available_endpoints: dict[str, Any] | None = None,
        db_session: Any = None,
        user_id: str | None = None,
    ) -> AnalysisPlan:
        """Generate an analysis plan from a structured intent.

        Retries the full LLM call + parse cycle on JSON parsing failures.
        """
        valid_skills = set(available_skills.keys()) if available_skills else VALID_SKILL_IDS
        valid_endpoints = set(available_endpoints.keys()) if available_endpoints else VALID_ENDPOINT_IDS

        complexity = self._get_complexity(intent)
        prompt = self._build_prompt(intent, complexity, db_session, user_id)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            if attempt > 0:
                await asyncio.sleep(1.0 * (2 ** (attempt - 1)))

            try:
                raw_output = await asyncio.wait_for(
                    self._invoke_llm(prompt),
                    timeout=self.llm_timeout,
                )
                plan_dict = parse_planning_llm_output(raw_output)
                plan = self._build_plan(plan_dict, complexity, intent)
                plan = self._validate_tasks(plan, valid_skills, valid_endpoints, complexity)
                return plan
            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning("Planning LLM timeout (attempt %d/%d)", attempt + 1, self.max_retries)
            except PlanningError as e:
                last_error = e
                logger.warning("Planning parse error (attempt %d/%d): %s", attempt + 1, self.max_retries, e)
            except Exception as e:
                last_error = e
                logger.warning("Planning error (attempt %d/%d): %s", attempt + 1, self.max_retries, e)

        raise PlanningError(
            f"规划失败: LLM 调用在 {self.max_retries} 次尝试后仍然失败: {last_error}"
        )

    def _get_complexity(self, intent: dict) -> str:
        """Extract output_complexity from intent."""
        # Direct key
        if "output_format" in intent and intent["output_format"] in TASK_COUNT_LIMITS:
            return intent["output_format"]
        if "output_complexity" in intent:
            return intent["output_complexity"]
        # From slots dict
        slots = intent.get("slots", {})
        if isinstance(slots, dict):
            comp_slot = slots.get("output_complexity", {})
            if isinstance(comp_slot, dict):
                val = comp_slot.get("value")
                if val and val in TASK_COUNT_LIMITS:
                    return val
        return "simple_table"

    def _build_prompt(
        self,
        intent: dict,
        complexity: str,
        db_session: Any = None,
        user_id: str | None = None,
    ) -> str:
        """Build the planning LLM prompt."""
        # Extract domain hint from intent
        domain_hint = intent.get("domain")
        if not domain_hint:
            slots = intent.get("slots", {})
            if isinstance(slots, dict):
                domain_slot = slots.get("domain", {})
                if isinstance(domain_slot, dict):
                    domain_hint = domain_slot.get("value")

        intent_json = json.dumps(intent, ensure_ascii=False, indent=2, default=str)
        skills_desc = get_skills_description()
        endpoints_desc = get_endpoints_description(domain_hint)

        # Template hint
        template_hint = ""
        # Template lookup is deferred to integration (requires async DB)

        # Report hint
        report_hint = ""
        if complexity == "full_report":
            report_hint = '注意：full_report 场景必须填充 report_structure 字段，包含 "sections" 列表。'

        return PLANNING_PROMPT.format(
            intent_json=intent_json,
            skills_description=skills_desc,
            endpoints_description=endpoints_desc,
            template_hint=template_hint,
            complexity=complexity,
            report_hint=report_hint,
        )

    def _build_plan(
        self, plan_dict: dict, complexity: str, intent: dict
    ) -> AnalysisPlan:
        """Build AnalysisPlan from parsed LLM output."""
        tasks = []
        for t_dict in plan_dict.get("tasks", []):
            tasks.append(TaskItem(
                task_id=t_dict.get("task_id", f"T{len(tasks)+1:03d}"),
                type=t_dict.get("type", "data_fetch"),
                name=t_dict.get("name", ""),
                description=t_dict.get("description", ""),
                depends_on=t_dict.get("depends_on", []),
                skill=t_dict.get("skill", ""),
                params=t_dict.get("params", {}),
                estimated_seconds=t_dict.get("estimated_seconds", 10),
            ))

        report_structure = plan_dict.get("report_structure")

        return AnalysisPlan(
            plan_id=str(uuid4()),
            version=1,
            title=plan_dict.get("title", "分析方案"),
            analysis_goal=plan_dict.get("analysis_goal", ""),
            estimated_duration=plan_dict.get("estimated_duration", sum(t.estimated_seconds for t in tasks)),
            tasks=tasks,
            report_structure=report_structure,
            revision_log=[],
        )

    def _validate_tasks(
        self,
        plan: AnalysisPlan,
        valid_skills: set[str],
        valid_endpoints: set[str],
        complexity: str,
    ) -> AnalysisPlan:
        """Validate tasks: filter hallucinated skills/endpoints, cap count, break cycles."""
        original_count = len(plan.tasks)
        filtered_tasks = []

        for task in plan.tasks:
            # Check skill validity
            if task.skill and task.skill not in valid_skills:
                logger.warning(
                    "Filtering task %s: hallucinated skill '%s'",
                    task.task_id, task.skill,
                )
                continue

            # Check endpoint validity (with M-code resolution)
            endpoint_id = task.params.get("endpoint_id")
            if endpoint_id and endpoint_id not in valid_endpoints:
                # Try resolving M-code (e.g. "M03" → "getThroughputTrendByMonth")
                resolved = resolve_endpoint_id(endpoint_id)
                if resolved and resolved in valid_endpoints:
                    logger.info(
                        "Resolved M-code '%s' → '%s' for task %s",
                        endpoint_id, resolved, task.task_id,
                    )
                    task.params["endpoint_id"] = resolved
                else:
                    logger.warning(
                        "Filtering task %s: hallucinated endpoint '%s'",
                        task.task_id, endpoint_id,
                    )
                    continue

            filtered_tasks.append(task)

        if len(filtered_tasks) < original_count:
            logger.warning(
                "Filtered %d hallucinated tasks (from %d to %d)",
                original_count - len(filtered_tasks),
                original_count,
                len(filtered_tasks),
            )

        # Cap task count at max for complexity
        _, max_count = TASK_COUNT_LIMITS.get(complexity, (1, 8))
        if len(filtered_tasks) > max_count:
            logger.warning(
                "Capping task count from %d to %d (max for %s)",
                len(filtered_tasks), max_count, complexity,
            )
            filtered_tasks = filtered_tasks[:max_count]

        # Fix dependency references (remove deps to filtered-out tasks)
        valid_task_ids = {t.task_id for t in filtered_tasks}
        for task in filtered_tasks:
            task.depends_on = [d for d in task.depends_on if d in valid_task_ids]

        plan.tasks = filtered_tasks

        # Break cycles
        plan.tasks = _break_cycles(plan.tasks)

        return plan

    async def _call_llm_with_retry(self, prompt: str) -> str:
        """Call LLM with timeout and retry logic."""
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            if attempt > 0:
                await asyncio.sleep(1.0 * (2 ** (attempt - 1)))

            try:
                result = await asyncio.wait_for(
                    self._invoke_llm(prompt),
                    timeout=self.llm_timeout,
                )
                return result
            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(
                    "Planning LLM timeout (attempt %d/%d)",
                    attempt + 1, self.max_retries,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "Planning LLM error (attempt %d/%d): %s",
                    attempt + 1, self.max_retries, e,
                )

        raise PlanningError(
            f"规划失败: LLM 调用在 {self.max_retries} 次尝试后仍然失败: {last_error}"
        )

    async def _invoke_llm(self, prompt: str) -> str:
        """Invoke the LLM and return raw text output."""
        if self.llm is None:
            raise PlanningError("LLM client not configured")

        if callable(self.llm) and not hasattr(self.llm, "ainvoke"):
            result = await self.llm(prompt)
            return str(result)

        response = await self.llm.ainvoke(prompt)
        if hasattr(response, "content"):
            return response.content
        return str(response)


# ── Plan Formatting ──────────────────────────────────────────

TYPE_LABELS = {
    "data_fetch": "数据获取",
    "search": "信息检索",
    "analysis": "分析处理",
    "visualization": "可视化",
    "report_gen": "报告生成",
}


def format_plan_as_markdown(plan: AnalysisPlan) -> str:
    """Format an AnalysisPlan as user-facing Markdown."""
    total_seconds = plan.estimated_duration or sum(t.estimated_seconds for t in plan.tasks)
    if total_seconds >= 60:
        time_str = f"约 {total_seconds // 60} 分钟"
    else:
        time_str = f"约 {total_seconds} 秒"

    lines = [
        f"**分析方案 · v{plan.version}**（预计完成时间：{time_str}）",
        "",
        f"**分析目标：** {plan.analysis_goal or plan.title}",
        "",
        "任务清单：",
    ]

    for task in plan.tasks:
        type_label = TYPE_LABELS.get(task.type, task.type)
        ep_id = task.params.get("endpoint_id", "")
        ep_info = ""
        if ep_id:
            ep_meta = ENDPOINT_REGISTRY.get(ep_id, {})
            ep_info = f"\n   → 来源：{ep_id}（{ep_meta.get('id', '')}），{ep_meta.get('when_to_use', '')}"

        lines.append(
            f"  {task.task_id} · {task.name} _({type_label} · 预计 {task.estimated_seconds} 秒)_"
            f"{ep_info}"
        )

    lines.extend([
        "",
        "---",
        "[确认执行] [修改方案] [重新规划]",
    ])

    return "\n".join(lines)


# ── Plan Update & Versioning ─────────────────────────────────

def update_plan(
    plan: AnalysisPlan,
    modifications: list[dict[str, Any]],
) -> AnalysisPlan:
    """Apply modifications to a plan and create a new version.

    Supported modifications:
      - {"type": "remove_task", "task_id": "T002"}
      - {"type": "add_task", "task": {...}}

    Returns a new AnalysisPlan with incremented version.
    """
    new_plan = plan.model_copy(deep=True)
    new_plan.version = plan.version + 1
    change_summaries = []

    for mod in modifications:
        mod_type = mod.get("type", "")

        if mod_type == "remove_task":
            target_id = mod.get("task_id", "")
            before_count = len(new_plan.tasks)
            new_plan.tasks = [t for t in new_plan.tasks if t.task_id != target_id]
            if len(new_plan.tasks) < before_count:
                # Clean up dependencies referencing the removed task
                for task in new_plan.tasks:
                    task.depends_on = [d for d in task.depends_on if d != target_id]
                change_summaries.append(f"remove_task {target_id}")

        elif mod_type == "add_task":
            task_dict = mod.get("task", {})
            if task_dict:
                new_plan.tasks.append(TaskItem(**task_dict))
                change_summaries.append(f"add_task {task_dict.get('task_id', '?')}")

    # Update estimated duration
    new_plan.estimated_duration = sum(t.estimated_seconds for t in new_plan.tasks)

    # Append revision log entry
    new_plan.revision_log.append({
        "version": new_plan.version,
        "changed_at": datetime.now().isoformat(),
        "change_summary": "; ".join(change_summaries) if change_summaries else "modifications applied",
    })

    return new_plan


async def regenerate_plan(
    original_plan: AnalysisPlan,
    feedback: str,
    engine: PlanningEngine,
    intent: dict[str, Any],
    **kwargs: Any,
) -> AnalysisPlan:
    """Regenerate a plan based on user feedback.

    Injects the feedback into the planning prompt and generates a new version.
    """
    # Add feedback to intent for re-planning
    augmented_intent = dict(intent)
    augmented_intent["user_feedback"] = feedback
    augmented_intent["previous_plan_summary"] = {
        "version": original_plan.version,
        "title": original_plan.title,
        "task_count": len(original_plan.tasks),
    }

    new_plan = await engine.generate_plan(augmented_intent, **kwargs)
    new_plan.version = original_plan.version + 1
    new_plan.revision_log = list(original_plan.revision_log)
    new_plan.revision_log.append({
        "version": new_plan.version,
        "changed_at": datetime.now().isoformat(),
        "change_summary": f"重新规划 (feedback: {feedback})",
    })
    return new_plan


# ── Template Lookup ──────────────────────────────────────────

async def find_templates(
    db_session: Any,
    user_id: str,
    domain: str | None = None,
    output_complexity: str | None = None,
) -> list[dict]:
    """Find historical analysis templates from MySQL.

    First tries exact match (domain + complexity), then domain-only fallback.
    Returns empty list if no templates found.
    """
    if db_session is None:
        return []

    from sqlalchemy import text

    # Exact match
    result = await db_session.execute(
        text("""
            SELECT name, plan_skeleton, usage_count
            FROM analysis_templates
            WHERE user_id = :uid
              AND (:domain IS NULL OR domain = :domain)
              AND (:complexity IS NULL OR output_complexity = :complexity)
            ORDER BY usage_count DESC
            LIMIT 3
        """),
        {"uid": user_id, "domain": domain, "complexity": output_complexity},
    )
    templates = [
        {"name": row[0], "plan_skeleton": row[1], "usage_count": row[2]}
        for row in result
    ]

    if not templates and domain:
        # Fallback: domain-only match
        result = await db_session.execute(
            text("""
                SELECT name, plan_skeleton, usage_count
                FROM analysis_templates
                WHERE user_id = :uid AND domain = :domain
                ORDER BY usage_count DESC
                LIMIT 3
            """),
            {"uid": user_id, "domain": domain},
        )
        templates = [
            {"name": row[0], "plan_skeleton": row[1], "usage_count": row[2]}
            for row in result
        ]

    return templates
