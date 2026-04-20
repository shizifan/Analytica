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
from backend.agent.skills import get_valid_skill_ids, get_skills_description
from backend.agent.api_registry import (
    VALID_ENDPOINT_IDS,
    get_endpoint,
    get_endpoints_description,
    resolve_endpoint_id,
)

logger = logging.getLogger("analytica.planning")

# ── Task count limits per complexity ─────────────────────────

TASK_COUNT_LIMITS = {
    "simple_table": (1, 3),
    "chart_text":   (2, 5),
    "full_report":  (5, 25),  # 模板最多23任务
}

# ── Template Hint 开关 ────────────────────────────────────────
ENABLE_TEMPLATE_HINT   = True   # 从 DB 查历史模板注入 prompt
ENABLE_TEMPLATE_BYPASS = True   # 命中 trigger_keywords 时直接返回模板，跳过 LLM

# ── 业务规则常量（可单独维护）────────────────────────────────

PLANNING_RULE_HINTS = {
    "minimization": (
        "- 优先使用最少的 data_fetch 任务。能用一个 API 满足的需求，不要用多个\n"
        "- chart_text 典型结构：1 个 data_fetch + 1 个 visualization = 2 个任务\n"
        "- 不要为了凑任务数而添加冗余数据获取（如同时查全港+分港区+分板块）\n"
        "- attribution_needed=false 或用户说\"不需要归因\"时，不生成归因分析任务"
    ),
    "time_param": (
        "【时间参数推导规则】\n"
        "intent 中 time_range 格式: {start: \"YYYY-MM-DD\", end: \"YYYY-MM-DD\", description: \"...\"}\n"
        "按端点要求的参数名推导：\n"
        "- date → end 月份 \"YYYY-MM\"\n"
        "- curDateYear → end 年份 \"YYYY\"；yearDateYear → (end年-1) \"YYYY\"\n"
        "- curDateMonth → end 月份 \"YYYY-MM\"；yearDateMonth → (end年-1)同月 \"YYYY-MM\"\n"
        "- startDate / endDate → start 的 \"YYYY-MM\" / end 的 \"YYYY-MM\"\n"
        "- zoneName → 仅在用户明确提及港区时填写，否则不包含此参数\n"
        "- businessSegment → 仅在用户明确提及业务板块时填写"
    ),
    "cargo_selection": (
        "【货类匹配原则】\n"
        "- 用户未明确指定具体货类（如\"集装箱\"\"散杂货\"\"商品车\"等）时，必须使用综合吞吐量端点\n"
        "  （如 getThroughputAndTargetThroughputTon、getThroughputAnalysisByYear），严禁使用集装箱专用端点\n"
        "  （如 getContainerThroughputAnalysisByYear、getThroughputAnalysisContainer、getThroughputAndTargetThroughputTeu）\n"
        "- 只有用户明确提到\"集装箱\"\"TEU\"\"箱量\"等关键词时才可使用集装箱专用端点\n\n"
        "【月度区间选端规则】\n"
        "- 当 time_range 跨越多个月份（如\"1-4月\"\"Q1\"\"上半年\"），且用户未明确要求\"累计/汇总/合计\"时，\n"
        "  必须选择 T_TREND 类型端点（如 getThroughputAnalysisByYear、getContainerThroughputAnalysisByYear），\n"
        "  返回按月拆分的趋势数据\n"
        "- 仅当用户明确说\"累计\"\"汇总\"\"总计\"时才选 T_CUM 累计端点"
    ),
}

# ── Planning LLM Prompt ──────────────────────────────────────

PLANNING_PROMPT = """你是一个数据分析规划专家。根据用户的分析意图，制定一份分析执行方案。

【分析意图】
{intent_json}

【可用技能清单】
{skills_description}

【可用数据端点】
{endpoints_description}

{structured_hints}
{template_hint}

【任务数量要求】
- simple_table: 1-3 个任务
- chart_text: 2-5 个任务
- full_report: 5-25 个任务
当前复杂度: {complexity}

{minimization_rules}
{time_param_rules}
{cargo_selection_rules}

【重要约束】
0. 每个 data_fetch 任务必须包含该端点要求的所有必填参数（见端点定义中"必填参数"行），严禁遗漏
1. 所有任务的 skill 字段必须从上方「可用技能清单」中选取
2. 所有 data_fetch 类任务的 params.endpoint_id 必须从上方「可用数据端点」中选取（使用真实 API 函数名）
3. getTrendChart 的 businessSegment 为【必填】参数
4. depends_on 引用的 task_id 必须在 tasks 列表中存在，不能有循环依赖
5. 集装箱有 TEU 和吨双单位，不可直接加总
6. task_id 按 T001, T002, ... 编号
7. 集装箱 TEU 专项查询请优先使用 getThroughputAndTargetThroughputTeu，而非市场域端点
8. 生产域(D1)与市场域(D2)的"吞吐量"口径不同：生产视角用 D1 域端点，市场视角用 D2 域端点

【技能激活规则】（根据 output_complexity 强制执行）
■ simple_table（1-3任务）：
  - 只允许 skill_api_fetch + skill_summary_gen（可选）
  - 禁止生成 visualization / analysis / report_gen 任务

■ chart_text（2-5任务）：
  - 必须≥1个 skill_api_fetch + ≥1个图表技能（skill_chart_bar / skill_chart_line / skill_chart_waterfall）
  - 允许1个 skill_desc_analysis 做文字解读
  - 禁止 report_gen，禁止 skill_attribution

■ full_report（5-25任务，必须全链路）：
  - 数据层：≥4个 skill_api_fetch，覆盖主指标 + 对比基线 + 结构分布 + 趋势
  - 分析层：≥2个 skill_desc_analysis + 1个 skill_attribution（attribution_needed=false 时可省略 skill_attribution）
  - 可视化层：≥3个图表技能
  - 汇总层：1个 skill_summary_gen（depends_on 所有分析层任务）
  - 报告层：1个 skill_report_html / skill_report_docx / skill_report_pptx（必须最后一个任务）
  - 典型链路：data_fetch × N → analysis × M → visualization × K → summary × 1 → report_gen × 1

【多数据源分析指引】
- 归因分析(attribution)：查找变化原因时，应获取重点企业贡献(getKeyEnterprise)或板块占比(getCurrentBusinessSegmentThroughput)等辅助数据
- 同比/环比对比：需要多期数据时，考虑趋势端点(getThroughputMonthlyTrend/getTrendChart)配合区域对比(getMonthlyZoneThroughput)或板块对比(getCompanyStatisticsBusinessType)
- 跨域分析：涉及多个领域（如"资产+投资"）时，应分别从各域获取数据（如 D5 资产域 + D6 投资域端点）
- 投资进度分析：月度执行节奏用 getPlanProgressByMonth，年度完成率/计划汇总用 getInvestPlanTypeProjectList，偏差分析建议两者配合
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

如果是 full_report 场景，report_structure 应包含报告章节结构，每个章节必须通过 task_refs 指定其内容来源的任务 ID：
{{"sections": [{{"name": "章节名称", "task_refs": ["T001", "T002"]}}, ...]}}
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


def _is_multi_month_range(time_range_value: dict | None) -> tuple[bool, int]:
    """Detect whether a time_range value spans multiple calendar months.

    Returns (is_multi_month, month_count). Safe on malformed input.
    """
    if not isinstance(time_range_value, dict):
        return False, 0
    start_str = time_range_value.get("start", "")
    end_str = time_range_value.get("end", "")
    if not start_str or not end_str:
        return False, 0
    try:
        sy, sm = int(start_str[:4]), int(start_str[5:7])
        ey, em = int(end_str[:4]), int(end_str[5:7])
        month_count = (ey - sy) * 12 + (em - sm) + 1
        return month_count >= 2, month_count
    except (ValueError, IndexError):
        return False, 0


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


def _apply_time_params(plan: AnalysisPlan, intent: dict) -> AnalysisPlan:
    """将模板中的占位时间参数替换为 intent 中的实际时间值。"""
    import copy
    slots = intent.get("slots", {})
    tr = (slots.get("time_range") or {}) if isinstance(slots, dict) else {}
    tr_val = tr.get("value") if isinstance(tr, dict) else None
    if not isinstance(tr_val, dict):
        return plan

    end_str   = tr_val.get("end", "")
    start_str = tr_val.get("start", "")
    end_year  = end_str[:4]
    end_month = end_str[:7]
    prev_year = str(int(end_year) - 1) if end_year.isdigit() else end_year

    replacements = {
        "2026-04-30": end_str,
        "2026-04-01": start_str,
        "2026-04":    end_month,
        "2026-01":    start_str[:7],
        "2026":       end_year,
        "2025":       prev_year,
    }
    plan_dict = copy.deepcopy(plan.model_dump())
    plan_str  = json.dumps(plan_dict, ensure_ascii=False)
    for old, new in replacements.items():
        if new:
            plan_str = plan_str.replace(f'"{old}"', f'"{new}"')
    updated = json.loads(plan_str)
    updated.pop("plan_id", None)
    return AnalysisPlan(**updated)


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
        allowed_endpoints: frozenset[str] | None = None,
        allowed_skills: frozenset[str] | None = None,
        prompt_suffix: str = "",
        employee_id: str | None = None,
    ) -> AnalysisPlan:
        """Generate an analysis plan from a structured intent.

        Retries the full LLM call + parse cycle on JSON parsing failures.

        Args:
            allowed_endpoints: 端点白名单 frozenset（来自 EmployeeProfile），硬过滤。
            allowed_skills: 技能白名单 frozenset（来自 EmployeeProfile），硬过滤。
            prompt_suffix: 员工规划层提示后缀。
            employee_id: 员工 ID，用于模板匹配。
        """
        # 确定合法技能集
        if allowed_skills is not None:
            valid_skills = get_valid_skill_ids(allowed_skills)
        elif available_skills:
            valid_skills = set(available_skills.keys())
        else:
            valid_skills = get_valid_skill_ids()

        # 确定合法端点集
        if allowed_endpoints is not None:
            valid_endpoints = set(allowed_endpoints)
        elif available_endpoints:
            valid_endpoints = set(available_endpoints.keys())
        else:
            valid_endpoints = VALID_ENDPOINT_IDS

        complexity = self._get_complexity(intent)

        # Template bypass: 命中 trigger_keywords 时直接返回模板，跳过 LLM
        if ENABLE_TEMPLATE_BYPASS and employee_id and complexity == "full_report":
            try:
                from backend.agent.plan_templates import match_template
                raw_query = intent.get("raw_query", "") or intent.get("query", "")
                bypassed = match_template(employee_id, raw_query, complexity)
                if bypassed is not None:
                    bypassed = _apply_time_params(bypassed, intent)
                    logger.info("Template bypass: employee=%s, tasks=%d", employee_id, len(bypassed.tasks))
                    return bypassed
            except Exception as e:
                logger.warning("Template bypass failed, fallback to LLM: %s", e)

        # Template hint: 优先 JSON 模板骨架，其次查 DB 历史模板
        if ENABLE_TEMPLATE_HINT:
            template_hint = await self._fetch_template_hint(intent, db_session, user_id, employee_id, complexity)
        else:
            template_hint = ""

        prompt = self._build_prompt(
            intent, complexity, db_session, user_id,
            available_skills=available_skills,
            allowed_endpoints=allowed_endpoints,
            allowed_skills=allowed_skills,
            prompt_suffix=prompt_suffix,
            template_hint=template_hint,
        )

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
        available_skills: dict[str, Any] | None = None,
        allowed_endpoints: frozenset[str] | None = None,
        allowed_skills: frozenset[str] | None = None,
        prompt_suffix: str = "",
        template_hint: str = "",
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

        # Extract new structured hints from slots
        comparison_type = None
        region_val = None
        data_granularity = None
        slots = intent.get("slots", {})
        if isinstance(slots, dict):
            for key in ("comparison_type", "region", "data_granularity"):
                slot = slots.get(key, {})
                if isinstance(slot, dict):
                    v = slot.get("value")
                    if v:
                        if key == "comparison_type":
                            comparison_type = v
                        elif key == "region":
                            region_val = v
                        elif key == "data_granularity":
                            data_granularity = v

        # Convert to registry filter hints
        from backend.agent.api_registry import COMPARISON_TO_TIME, GRANULARITY_MAP, DOMAIN_INDEX
        # Handle list comparison_type (multiple comparison types)
        if isinstance(comparison_type, list):
            time_hint = None
            for ct in comparison_type:
                hint = COMPARISON_TO_TIME.get(ct)
                if hint:
                    time_hint = hint
                    break
        else:
            time_hint = COMPARISON_TO_TIME.get(comparison_type) if comparison_type else None
        granularity_hint = GRANULARITY_MAP.get(data_granularity) if data_granularity else None

        # Auto-detect multi-month range → prefer T_TREND endpoints
        multi_month_detected = False
        multi_month_count = 0
        if time_hint is None and comparison_type is None:
            tr_slot = slots.get("time_range", {}) if isinstance(slots, dict) else {}
            tr_val = tr_slot.get("value") if isinstance(tr_slot, dict) else None
            if tr_val is None:
                tr_val = intent.get("time_range")
            is_multi, mc = _is_multi_month_range(tr_val)
            if is_multi:
                time_hint = {"T_TREND"}
                multi_month_detected = True
                multi_month_count = mc
                logger.info("Auto-set time_hint=T_TREND for multi-month range (%d months)", mc)

        intent_json = json.dumps(intent, ensure_ascii=False, indent=2, default=str)

        # Use available_skills descriptions when provided, else default registry
        if available_skills:
            lines = []
            for skill_id, info in available_skills.items():
                desc = info.get("description", "")
                inp = info.get("input", "")
                out = info.get("output", "")
                lines.append(f"- {skill_id}: {desc}")
                if inp or out:
                    lines.append(f"  输入: {inp} → 输出: {out}")
            skills_desc = "\n".join(lines)
        elif allowed_skills is not None:
            skills_desc = get_skills_description(allowed_skills=allowed_skills)
        else:
            skills_desc = get_skills_description()

        endpoints_desc = get_endpoints_description(
            domain_hint, time_hint, granularity_hint,
            allowed_endpoints=allowed_endpoints,
                )

        # Report hint_hint = ""
        # Template lookup is deferred to integration (requires async DB)

        # Report hint: 5层链路规范
        report_hint = ""
        if complexity == "full_report":
            output_format = ""
            slots_inner = intent.get("slots", {})
            if isinstance(slots_inner, dict):
                fmt_slot = slots_inner.get("output_format", {})
                if isinstance(fmt_slot, dict):
                    output_format = (fmt_slot.get("value") or "").upper()
            if not output_format:
                output_format = (intent.get("output_format") or "").upper()

            format_skill_map = {
                "HTML": "skill_report_html",
                "DOCX": "skill_report_docx",
                "WORD": "skill_report_docx",
                "PPTX": "skill_report_pptx",
                "PPT": "skill_report_pptx",
            }
            report_skill = format_skill_map.get(output_format, "skill_report_html")

            attr_slot = slots_inner.get("attribution_needed", {}) if isinstance(slots_inner, dict) else {}
            attr_needed = attr_slot.get("value", True) if isinstance(attr_slot, dict) else True
            attr_note = "" if attr_needed else "\n  → attribution_needed=false，可省略 skill_attribution 任务"

            report_hint = (
                f"【full_report 报告生成规范】\n"
                f"报告格式: {output_format or 'HTML'}，报告技能: {report_skill}\n\n"
                f"必须按5层链路组织 tasks：\n"
                f"  Layer1 数据层（≥4）: skill_api_fetch × N（主KPI + 趋势序列 + 结构分布 + 对比基线）\n"
                f"  Layer2 分析层（≥2）: skill_desc_analysis + skill_attribution{attr_note}\n"
                f"    → 每个分析任务 depends_on 对应的数据层任务\n"
                f"  Layer3 可视化层（≥3）: skill_chart_bar / skill_chart_line / skill_chart_waterfall 组合\n"
                f"    → 每图 depends_on 1-2个数据层任务\n"
                f"  Layer4 汇总层（1）: skill_summary_gen，depends_on 所有分析层任务\n"
                f"  Layer5 报告层（1，必须最后）: {report_skill}\n"
                f"    → depends_on 所有可视化层 + 汇总层任务\n"
                f"    → estimated_seconds: 30\n"
                f"    → params 包含 report_metadata: {{title, author, date}}\n\n"
                f"report_structure 必须填充，格式:\n"
                f'  {{"sections": [{{"name": "章节名", "task_refs": ["T001", "T002"]}}, ...]}}\n'
                f"建议章节：一、概览 | 二、趋势分析 | 三、结构分析 | 四、归因分析 | 五、结论建议"
            )

        # Build structured hints block
        hint_lines = []
        if comparison_type:
            ct_map = {"yoy": "同比", "mom": "环比", "cumulative": "累计",
                      "trend": "趋势", "snapshot": "实时", "historical": "历史"}
            # Handle list comparison_type (multiple comparison types)
            if isinstance(comparison_type, list):
                ct_display = ", ".join(ct_map.get(v, v) for v in comparison_type if v in ct_map) or str(comparison_type[0])
                time_types = set()
                for ct in comparison_type:
                    time_types.update(COMPARISON_TO_TIME.get(ct, set()))
                time_types_display = ", ".join(sorted(time_types)) if time_types else ""
            else:
                ct_display = ct_map.get(comparison_type, comparison_type)
                time_types_display = ", ".join(sorted(COMPARISON_TO_TIME.get(comparison_type, set())))
            hint_lines.append(f"- 对比方式: {ct_display} → 优先选择 {time_types_display} 类型端点")
        if region_val:
            hint_lines.append(f'- 区域范围: {region_val} → 端点参数传 regionName/ownerZone="{region_val}"')
        if data_granularity:
            g_display = {"port": "全港", "zone": "港区", "company": "公司", "customer": "客户",
                         "equipment": "设备", "project": "项目", "cargo": "货类", "asset": "资产",
                         "business": "业务板块"}.get(data_granularity, data_granularity)
            hint_lines.append(f"- 数据粒度: {g_display} → 优先选择 {granularity_hint or ''} 粒度端点")
        if domain_hint:
            di = DOMAIN_INDEX.get(domain_hint)
            hint_lines.append(f"- 业务领域: {di.name if di else domain_hint} ({domain_hint})")
        # attribution_needed=false 提示
        attribution_slot = slots.get("attribution_needed", {})
        if isinstance(attribution_slot, dict) and attribution_slot.get("value") is False:
            hint_lines.append("- 归因分析: 用户明确不需要 → 不生成归因相关任务")
        if multi_month_detected:
            hint_lines.append(
                f"- 时间区间: 跨{multi_month_count}个月 → 已标记 T_TREND 月度趋势端点为优先，应选择返回按月拆分数据的端点"
            )

        # Merge employee Cookbook into structured_hints (higher salience)
        if prompt_suffix:
            if hint_lines:
                hint_lines.append(f"\n【员工专属规划提示（Cookbook）】\n{prompt_suffix}")
            else:
                hint_lines = [f"【员工专属规划提示（Cookbook）】\n{prompt_suffix}"]

        structured_hints = ("【意图结构化提示】\n" + "\n".join(hint_lines)) if hint_lines else ""

        result = PLANNING_PROMPT.format(
            intent_json=intent_json,
            skills_description=skills_desc,
            endpoints_description=endpoints_desc,
            structured_hints=structured_hints,
            template_hint=template_hint,
            complexity=complexity,
            report_hint=report_hint,
            minimization_rules=PLANNING_RULE_HINTS["minimization"],
            time_param_rules=PLANNING_RULE_HINTS["time_param"],
            cargo_selection_rules=PLANNING_RULE_HINTS["cargo_selection"],
        )
        return result

    async def _fetch_template_hint(
        self,
        intent: dict[str, Any],
        db_session: Any,
        user_id: str | None,
        employee_id: str | None = None,
        complexity: str = "",
    ) -> str:
        """模板提示注入：优先用 JSON 模板骨架（Few-Shot），其次查 DB 历史模板。"""
        # ── 优先：JSON 模板骨架（Few-Shot）──
        if employee_id and complexity == "full_report":
            try:
                from backend.agent.plan_templates import get_template_skeleton, TEMPLATE_REGISTRY
                if employee_id in TEMPLATE_REGISTRY:
                    skeleton = get_template_skeleton(employee_id)
                    return (
                        "【full_report 参考骨架（同员工模板，仅作结构参考，请根据当前意图调整 API 和参数）】\n"
                        f"{skeleton}\n\n"
                        "**注意：以上仅为结构示例，严禁照搬 endpoint_id 和 params，必须根据当前用户查询重新选择。**"
                    )
            except Exception as e:
                logger.warning("Template skeleton injection failed: %s", e)

        # ── 回退：DB 历史模板 ──
        if db_session is None or user_id is None:
            return ""
        try:
            from backend.agent.planning import find_templates
            domain = intent.get("domain")
            output_complexity = self._get_complexity(intent)
            templates = await find_templates(db_session, user_id, domain, output_complexity)
            if not templates:
                return ""
            lines = ["【历史模板参考】"]
            for t in templates[:3]:
                lines.append(f"- {t['name']} (使用{t['usage_count']}次):")
                lines.append(f"  {t['plan_skeleton'][:200]}")
            return "\n".join(lines)
        except Exception:
            return ""

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

            # Validate required params for data_fetch tasks
            if task.type == "data_fetch" and endpoint_id:
                ep = get_endpoint(endpoint_id)
                if ep and ep.required:
                    query_params = {k: v for k, v in task.params.items() if k != "endpoint_id"}
                    missing = [p for p in ep.required if p not in query_params]
                    if missing:
                        logger.warning(
                            "Filtering task %s: endpoint %s missing required params: %s",
                            task.task_id, endpoint_id, ", ".join(missing),
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

        # Cap task count at max for complexity, preserving report_gen tasks
        _, max_count = TASK_COUNT_LIMITS.get(complexity, (1, 8))
        if len(filtered_tasks) > max_count:
            # Separate report_gen tasks from other tasks so they aren't truncated
            report_tasks = [t for t in filtered_tasks if t.type == "report_gen"]
            non_report_tasks = [t for t in filtered_tasks if t.type != "report_gen"]
            # Reserve slots for report tasks, cap non-report tasks
            non_report_cap = max(max_count - len(report_tasks), 1)
            if len(non_report_tasks) > non_report_cap:
                non_report_tasks = non_report_tasks[:non_report_cap]
            filtered_tasks = non_report_tasks + report_tasks
            logger.warning(
                "Capped task count from %d to %d (max for %s, preserved %d report_gen tasks)",
                original_count, len(filtered_tasks), complexity, len(report_tasks),
            )

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
            ep_meta = get_endpoint(ep_id)
            ep_intent = ep_meta.intent if ep_meta else ""
            ep_info = f"\n   → 来源：{ep_id}，{ep_intent}"

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
