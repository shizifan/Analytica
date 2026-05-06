"""PlanningEngine — 规划层核心。

接收感知层输出的 StructuredIntent，调用 LLM 生成 AnalysisPlan，
验证工具/端点合法性，提供 Markdown 展示和版本管理。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from backend.exceptions import PlanningError
from backend.models.schemas import AnalysisPlan, TaskItem
from backend.tracing import trace_span
from backend.agent._complexity_rules import (
    CHART_TOOLS,
    COMPLEXITY_RULES,
    DATA_SOURCE_TOOLS,
    REPORT_FILE_TOOLS,
    get_rule,
    get_task_count_hint,
)
from backend.agent.tools import get_valid_tool_ids, get_tools_description
from backend.agent.api_registry import (
    VALID_ENDPOINT_IDS,
    get_endpoint,
    get_endpoints_description,
    resolve_endpoint_id,
)

logger = logging.getLogger("analytica.planning")

# ── Template Hint 开关 ────────────────────────────────────────
ENABLE_TEMPLATE_HINT   = True   # 从 DB 查历史模板注入 prompt
ENABLE_TEMPLATE_BYPASS = True   # 命中 trigger_keywords 时直接返回模板，跳过 LLM

# ── Multi-round planning（full_report 专用）──────────────────
# full_report 始终走多轮：先生成 skeleton（章节大纲），再并行填充每节的具体
# 任务，最后由 _stitch_plan 拼接全局任务。多轮失败时自动回退到下方的单轮
# 路径，所以单轮兜底依然是稳态保障。
_PLANNING_SKELETON_TIMEOUT     = float(os.getenv("PLANNING_SKELETON_TIMEOUT", "60"))
_PLANNING_SECTION_TIMEOUT      = float(os.getenv("PLANNING_SECTION_TIMEOUT",  "60"))
_PLANNING_SECTION_PARALLELISM  = int(os.getenv("PLANNING_SECTION_PARALLELISM", "5"))
_PLANNING_SECTION_FAILURE_RATIO = float(os.getenv("PLANNING_SECTION_FAILURE_RATIO", "0.4"))
_MAX_FINDING_LEN               = 200  # max chars per finding in multi-turn context

# ── 业务规则常量（可单独维护）────────────────────────────────

PLANNING_RULE_HINTS = {
    "minimization": (
        "- 优先使用最少的 data_fetch 任务。能用一个 API 满足的需求, 不要用多个\n"
        "- chart_text 任务由数据复杂度决定: 简单查询 1-2 个任务即可, 复杂分析可以更多\n"
        "- 不要为了凑任务数添加冗余数据获取\n"
        "- attribution_needed=false 或用户说\"不需要归因\"时, 不生成归因分析任务\n"
        "- predictive_needed=false 或用户没问\"预测/未来\"时, 不生成预测任务"
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


def resolve_rule_hint(key: str, overrides: dict[str, str] | None) -> str:
    """Apply per-employee ``rule_hints`` overrides to the global hint table.

    P3.2 semantics:
      * key not present in ``overrides`` → return the global default
      * key present with empty string  → return "" (skip this rule)
      * key present with non-empty str  → return the override

    Used by both single-round and multi-round prompt builders so the same
    employee config drives all planning paths consistently.
    """
    overrides = overrides or {}
    if key in overrides:
        return overrides[key]
    return PLANNING_RULE_HINTS.get(key, "")


def _extract_time_hints(intent: dict[str, Any]) -> dict[str, str] | None:
    """从 intent 的 time_range slot 提取具体时间参数候选值。

    用于注入 section prompt，减少 LLM 自行解析 JSON 并推导
    参数值时的遗漏概率（Tier 1 核心优化）。
    """
    slots = intent.get("slots", {})
    if not isinstance(slots, dict):
        return None

    tr = slots.get("time_range", {})
    if not isinstance(tr, dict):
        return None

    tr_val = tr.get("value")
    if not isinstance(tr_val, dict):
        return None

    start = tr_val.get("start", "")
    end = tr_val.get("end", "")

    hints: dict[str, str] = {}
    if start:
        hints["startDate"] = start
    if end:
        hints["endDate"] = end
        if "-" in end:
            hints["dateYear"] = end[:4]       # "2026-03-31" → "2026"
            hints["dateMonth"] = end[:7]      # "2026-03-31" → "2026-03"
            hints["date"] = end               # 完整日期
    return hints if hints else None


# ── Planning LLM Prompt ──────────────────────────────────────

PLANNING_PROMPT = """你是一个数据分析规划专家。根据用户的分析意图，制定一份分析执行方案。

{multiturn_context}

【分析意图】
{intent_json}

【可用工具清单】
{tools_description}

【可用数据端点】
{endpoints_description}

{agent_skills_hint}{structured_hints}
{template_hint}

【任务数量建议】（仅供参考, 实际由数据复杂度决定）
- simple_table: 1-2 个任务（典型 1 个）
- chart_text:   1-8 个任务（典型 4 个；按数据需要灵活调整）
- full_report:  3-20 个任务（典型 8 个；包含完整数据→分析→可视化→报告链路）
当前复杂度: {complexity}

{minimization_rules}
{time_param_rules}
{cargo_selection_rules}

【重要约束】
0. 每个 data_fetch 任务必须包含该端点要求的所有必填参数（见端点定义中"必填参数"行），严禁遗漏
1. 所有任务的 tool 字段必须从上方「可用工具清单」中选取
2. 所有 data_fetch 类任务的 params.endpoint_id 必须从上方「可用数据端点」中选取（使用真实 API 函数名）
3. getTrendChart 的 businessSegment 为【必填】单值参数，每次调用只能传一个板块名称（字符串，非列表）；若需查询多个板块，必须拆分为多个独立的 data_fetch 任务，每个任务各自传一个 businessSegment
4. depends_on 引用的 task_id 必须在 tasks 列表中存在，不能有循环依赖
5. 集装箱有 TEU 和吨双单位，不可直接加总
6. task_id 按 T001, T002, ... 编号
7. 集装箱 TEU 专项查询请优先使用 getThroughputAndTargetThroughputTeu，而非市场域端点
8. 生产域(D1)与市场域(D2)的"吞吐量"口径不同：生产视角用 D1 域端点，市场视角用 D2 域端点
9. 端点粒度匹配：当用户明确要求"各机种"、"每种设备"、"机种对比"、"识别低效机种"等按机种分类的分析时，必须选择返回数据中包含 secondLevelClassName（机种）维度的端点，避免使用仅按港区汇总的端点（即使后者名称相似）。例如：设备按机种对比用 getProductionEquipmentStatistic，而非 getEquipmentUsageRate/getEquipmentServiceableRate（后者无按机种分类）
注意：参数值的细节约束（如某参数不能传特定字符串、传哪些可选参数）由数据获取层 LLM 自动处理，规划层只需关注结构（任务数量、依赖关系、端点选择）

【工具激活规则】（按复杂度区分; 验证层会强制 must / forbidden）
■ simple_table - 表格类查询:
  - 必须: tool_api_fetch 或 tool_file_parse (≥1, 选最合适的数据源)
  - 可选: tool_chart_* (如数据适合可视化, 与表格在同一卡片切换显示)
  - 可选: tool_web_search (需补充外部信息时)
  - 禁止: tool_desc_analysis / tool_attribution / tool_prediction / tool_anomaly / tool_summary_gen / tool_report_*

■ chart_text - 图文分析:
  - 必须: tool_api_fetch 或 tool_file_parse (≥1, 按数据需要)
  - 可选 (按数据需要灵活组合):
    - tool_chart_* - 当图表能更好展现分析结论时使用; 文字能说清就不必出图
    - tool_desc_analysis - 针对单个或多个 API 数据做描述性分析, 数量按需 (一份数据一段叙述, 或多份数据综合一段叙述)
    - tool_attribution - 当用户问"为什么/原因/归因"时使用
    - tool_prediction - 当用户问"未来/趋势预测"时使用
    - tool_anomaly - 当用户问"异常/反常/突变"时使用
    - tool_summary_gen - 多任务综合总结 (推荐作为最后一个任务)
    - tool_web_search - 需补充外部信息时
  - 禁止: tool_report_* (HTML / DOCX / PPTX / Markdown 文件输出, 共 4 个)

■ full_report - 图文分析 + 可下载文档:
  - 必须: tool_api_fetch 或 tool_file_parse (≥1) + tool_report_* (≥1, 任一报告工具, 必须是最后一个任务)
  - 可选: 同 chart_text 的全部可选工具 (鼓励完整链路: 数据 → 分析 → 可视化 → 总结 → 报告)
  - 禁止: 无

【重要】
- 任务工具应基于"数据是否需要"决定, 不要为了凑层级而生成冗余任务
- chart_text 与 full_report 的唯一区别是是否需要可下载文档 (HTML/DOCX/PPTX/Markdown)
- simple_table 始终不生成分析类工具 (desc / attribution / prediction / anomaly / summary)
- chart_text / full_report 内部, 是否生成 attribution/prediction/anomaly 任务由 attribution_needed/predictive_needed 等槽位决定

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
      "type": "data_fetch | search | analysis | visualization | summary | report_gen",
      "name": "任务名称",
      "description": "对用户友好的描述",
      "depends_on": [],
      "tool": "工具ID",
      "params": {{"endpoint_id": "端点ID", ...}},
      "estimated_seconds": 10
    }}
  ],
  "report_structure": null
}}

【visualization 任务特别规范】
visualization 类型任务必须使用 intent 字段描述图表意图，params 只写 chart_type，
禁止在 params 中写 x_field / y_fields / series_by / config 等列级配置
（这些由执行阶段根据真实数据自动决定）：
{{
  "task_id": "T003",
  "type": "visualization",
  "name": "生成月度吞吐量趋势折线图",
  "intent": "对比2026年与2025年各月吞吐量趋势变化，体现同比差异",
  "depends_on": ["T001"],
  "tool": "tool_chart_line",
  "params": {{"chart_type": "line"}},
  "estimated_seconds": 5
}}

【analysis 任务特别规范】
analysis 类型任务必须遵循「Planning 给意图，执行阶段看数据决策」原则：
- intent 字段描述分析目标（必填，越具体越好）
- params 仅写 data_ref（tool_desc_analysis）或留空（tool_attribution 直接读 depends_on）
- 禁止在 params 中写：target_columns / group_by / time_column / analysis_goal /
  focus_points / target_kpi / drivers / target_metric / time_period
  （这些由执行阶段根据真实数据和 intent 自动决定）

tool_desc_analysis 示例：
{{
  "task_id": "T004",
  "type": "analysis",
  "name": "描述性统计分析",
  "intent": "分析各港区吞吐量月度趋势与同比增速，找出高增长和下滑港区",
  "depends_on": ["T001"],
  "tool": "tool_desc_analysis",
  "params": {{"data_ref": "T001"}},
  "estimated_seconds": 30
}}

tool_attribution 示例（params 留空，上游数据通过 depends_on 自动注入）：
{{
  "task_id": "T006",
  "type": "analysis",
  "name": "吞吐量变化归因分析",
  "intent": "分析2026年1-4月吞吐量同比下降的主要驱动因素，结合港区和货种维度拆解贡献度",
  "depends_on": ["T001", "T002", "T003"],
  "tool": "tool_attribution",
  "params": {{}},
  "estimated_seconds": 45
}}

【search 任务特别规范】
search 类型任务用于通过互联网检索补充外部信息：
- type 为 "search" 时，params.query 应为搜索引擎意义上的关键词组合
- query 应优先包含行业/公司背景词（如"辽港集团"、"大连港"、"港航物流"）
- name 应包含搜索关键词，description 说明搜索原因
- 系统会自动追加领域前缀作为兜底，无需在 params.query 中重复

示例：
{{
  "task_id": "T002",
  "type": "search",
  "name": "搜索2026年航运市场趋势",
  "tool": "tool_web_search",
  "intent": "了解2026年全球航运市场宏观趋势",
  "description": "补充外部宏观经济信息，为归因分析提供外部因素参考",
  "depends_on": ["T001"],
  "params": {{"query": "辽港集团 集装箱 航运市场 2026年 趋势"}},
  "estimated_seconds": 10
}}

如果是 full_report 场景，report_structure 应包含报告章节结构，sections 只填章节名称，不写 task_refs（执行时自动关联）：
{{"sections": [{{"name": "章节名称"}}, ...]}}

【报告工具参数规范】
所有报告工具（tool_summary_gen / tool_report_html / tool_report_docx / tool_report_pptx）：
- 必须携带 "intent" 字段说明报告意图
- 禁止在 params 中写：summary_style / topic / domain / template_id / task_refs（这些由执行时 LLM 自动决定）
- tool_summary_gen params 示例：{{"intent": "分析港口吞吐量完成情况与归因"}}
- tool_report_* params 示例：{{"intent": "港口运营月度分析", "report_metadata": {{"title": "...", "author": "Analytica", "date": "..."}},"report_structure": {{"sections": [{{"name": "概览"}}, {{"name": "趋势分析"}}]}}}}
"""


# ── Multi-round prompts ───────────────────────────────────────
# Round 1: skeleton — only decides "how many sections, what they cover".
# Deliberately omits the full endpoint catalogue and the 5-layer pipeline rules
# so the prompt stays small and the LLM call finishes well under 60s.

SKELETON_PROMPT = """你是一个数据分析报告策划专家。根据用户分析意图，规划一份 full_report 的【章节结构】。
你只决定"分几节、每节讲什么"，不生成具体任务（任务由后续阶段按章节分别生成）。

【分析意图】
{intent_json}

【可选业务领域索引】
{domain_index}

【输出格式提示】
{output_formats_hint}

【任务说明】
1. 输出 4-6 个 section（章节）。典型结构：概览 / 趋势 / 结构 / 归因 / 结论。
2. 每个 section 必须给出：
   - section_id: "S1" / "S2" / ... 顺序编号
   - name: 章节名称
   - description: 1-2 句说明该节聚焦的问题（会传给下一阶段 LLM）
   - focus_metrics: 1-3 个核心指标
   - domain_hint: 业务域代号（D1-D7），用于反查可用端点
   - expected_task_count: 3-5（不含归因/汇总/报告，这些由系统自动补）
3. needs_attribution: 用户明确"不需要归因"时填 false，否则 true。
4. output_formats: 从用户意图的 output_format slot 提取，缺省 ["HTML"]。

【输出严格 JSON，无 <think> 块，无 markdown 包裹】
{{
  "title": "方案标题（简洁中文）",
  "analysis_goal": "分析目标一句话",
  "needs_attribution": true,
  "output_formats": ["HTML"],
  "sections": [
    {{
      "section_id": "S1",
      "name": "总体概览",
      "description": "聚焦本期吞吐量整体水平与同比变化",
      "focus_metrics": ["吞吐量", "同比增速"],
      "domain_hint": "D2",
      "expected_task_count": 3
    }}
  ]
}}
"""


# Round 2: per-section fill — only generates concrete tasks for ONE section,
# given a pre-filtered endpoint subset (by domain_hint). No global concerns
# (summary / report / attribution) — those are appended deterministically by
# _stitch_plan after all sections return.

SECTION_PROMPT = """你是一个数据分析任务规划专家。为下面这一【单个章节】生成具体任务。
**只生成 data_fetch / analysis / visualization 类型的任务**。
禁止生成 summary / report_gen / attribution 任务（由系统在合并阶段自动补）。

【章节信息】
section_id: {section_id}
name: {section_name}
description: {section_description}
focus_metrics: {focus_metrics}
expected_task_count: {expected_task_count}（允许 ±2）

【上游意图】
{intent_json}

【本章节可用端点（已按 domain_hint 过滤）】
{section_endpoints_desc}

【可用工具】
{tools_description}

{time_hints}

{required_warning}

{time_param_rules}

{cargo_selection_rules}
{employee_cookbook}
{error_feedback}
【硬约束】
- 所有 task_id 必须以 "{section_id}." 前缀，例如 {section_id}.T1, {section_id}.T2
- depends_on 只能引用本章节内的 task_id（跨章节依赖由汇总层处理）
- 至少 1 个 data_fetch 任务
- 如有 visualization，必须 depends_on 至少 1 个本章节内的 data_fetch
- analysis 任务遵循"intent 字段描述目标，params 只写 data_ref"原则
- visualization 任务遵循"intent 字段描述图表意图，params 只写 chart_type"原则
- 工具必须从【可用工具】清单中选取，端点必须从【本章节可用端点】中选取
- data_fetch 任务的 params 必须包含所选端点【端点必填参数总览】中列出的全部必填参数
- 时间类参数值必须使用【时间参数具体值】中的候选值

【输出严格 JSON，无 <think>，无 markdown】
{{
  "tasks": [
    {{
      "task_id": "{section_id}.T1",
      "type": "data_fetch",
      "name": "任务名",
      "description": "对用户友好的描述",
      "depends_on": [],
      "tool": "tool_api_fetch",
      "params": {{"endpoint_id": "端点名", "必填参数1": "值1", "必填参数2": "值2"}},
      "intent": "",
      "estimated_seconds": 10
    }}
  ]
}}
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


def _sanitize_report_structure(rs: Any) -> Any:
    """与 prompt 承诺对齐：sections 只保留 name/description，剥离 task_refs。

    LLM 偶尔会自作主张给某个 section 加 task_refs，触发 collector 的 strict
    匹配模式，导致其他 section 的任务输出被丢。统一在 plan 落盘前 strip 掉，
    强制走 round-robin 兜底分配。
    """
    if not isinstance(rs, dict):
        return rs
    sections = rs.get("sections")
    if not isinstance(sections, list):
        return rs
    stripped = 0
    for s in sections:
        if isinstance(s, dict) and "task_refs" in s:
            s.pop("task_refs", None)
            stripped += 1
    if stripped:
        logger.info(
            "[planning] sanitize_report_structure: stripped task_refs from %d/%d sections",
            stripped, len(sections),
        )
    return rs


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


# Per-complexity timeout (seconds): full_report needs more headroom for large models
_PLANNING_TIMEOUT_BY_COMPLEXITY: dict[str, float] = {
    "simple_table": 60.0,
    "chart_text":   90.0,
    "full_report":  180.0,
    "_default":     120.0,
}


def _add_task_id_prefix(tasks: list[TaskItem], turn_index: int) -> list[TaskItem]:
    """Prefix task_ids with R{turn_index}_ for multi-turn isolation.

    Round 0 tasks keep their original IDs. Round 1+ get R1_, R2_ prefixes.
    Also prefixes depends_on references to match.
    """
    if turn_index <= 0:
        return tasks

    prefix = f"R{turn_index}_"
    for t in tasks:
        if not t.task_id.startswith(prefix):
            old_id = t.task_id
            t.task_id = f"{prefix}{old_id}"
            t.depends_on = [
                f"{prefix}{d}" if not d.startswith(prefix) else d
                for d in t.depends_on
            ]
    return tasks


def _build_completed_plan_summary(plan_history: list[dict]) -> str:
    """Build a summary of completed tasks from archived plans."""
    if not plan_history:
        return "（无历史计划）"

    lines = []
    for p in plan_history:
        title = p.get("title", "")[:100]
        tasks = p.get("tasks", [])
        task_lines = []
        for t in tasks:
            tid = t.get("task_id", "?")
            ttype = t.get("type", "?")
            name = t.get("name", tid)
            ep = t.get("params", {}).get("endpoint_id", "")
            short = f"  - {tid} [{ttype}] {name[:60]}"
            if ep:
                short += f" (ep={ep})"
            task_lines.append(short)
        turn_label = p.get("turn_index", "?")
        lines.append(f"第 {turn_label} 轮: {title}\n" + "\n".join(task_lines[:10]))

    return "\n".join(lines)


def build_amend_plan(prev_state: dict, user_message: str) -> AnalysisPlan | None:
    """Build a minimal execution plan for amend turn (format add/replace).

    Key fix: does NOT depends_on previous turn's task_ids. Instead passes
    _previous_artifacts via params so the report tool can load them from DB.

    Returns AnalysisPlan, or None when format cannot be detected
    (caller should route to LLM planning).
    """
    from uuid import uuid4

    msg = user_message.lower().strip()
    turn_index = prev_state.get("turn_index", 0) + 1

    is_replace = any(kw in msg for kw in ["换成", "转成", "导出为", "改为"])

    fmt_map = {
        "pptx": "tool_report_pptx",
        "docx": "tool_report_docx",
        "word": "tool_report_docx",
        "html": "tool_report_html",
        "ppt": "tool_report_pptx",
        "markdown": "tool_report_markdown",
        "md": "tool_report_markdown",
    }

    # Short keywords ("word", "ppt", "md") use word-boundary matching
    # to avoid false positives (e.g. "word" in "keyword", "md" in "cmd").
    _word_boundary_keys = {"word", "ppt", "md"}

    detected_fmts: list[tuple[str, str]] = []
    for keyword, tool_id in fmt_map.items():
        if keyword in _word_boundary_keys:
            matched = bool(re.search(r'\b' + re.escape(keyword) + r'\b', msg))
        else:
            matched = keyword in msg
        if matched and tool_id not in [f for _, f in detected_fmts]:
            detected_fmts.append((keyword.upper(), tool_id))

    if not detected_fmts:
        logger.warning(
            "Amend fast path could not detect format from: %s", user_message[:80]
        )
        return None

    prev_turn = (prev_state.get("analysis_history") or [{}])[-1]
    prev_artifacts = prev_turn.get("artifacts", [])
    prev_findings = prev_turn.get("key_findings", [])
    prev_plan = prev_state.get("analysis_plan") or {}

    tasks: list[TaskItem] = []
    for fmt_label, tool_id in detected_fmts:
        tasks.append(TaskItem(
            task_id=f"R{turn_index}_REPORT_{fmt_label}",
            type="report_gen",
            name=f"生成{fmt_label}报告",
            description=f"{'追加' if not is_replace else ''}生成 {fmt_label} 格式报告",
            depends_on=[],
            tool=tool_id,
            params={
                "intent": prev_plan.get("analysis_goal", "数据分析报告"),
                "report_structure": prev_plan.get("report_structure"),
                "_previous_artifacts": prev_artifacts,
                "_previous_findings": prev_findings,
                "is_replace": is_replace,
            },
            intent=prev_plan.get("analysis_goal", ""),
            estimated_seconds=30,
        ))

    return AnalysisPlan(
        plan_id=str(uuid4()),
        version=1,
        turn_index=turn_index,
        parent_plan_id=prev_plan.get("plan_id"),
        title=f"[{'追加' if not is_replace else '格式转换'}] {prev_plan.get('title', '')}",
        analysis_goal=prev_plan.get("analysis_goal", ""),
        estimated_duration=sum(t.estimated_seconds for t in tasks),
        tasks=tasks,
        report_structure=prev_plan.get("report_structure"),
        revision_log=[],
    )


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
        available_tools: dict[str, Any] | None = None,
        available_endpoints: dict[str, Any] | None = None,
        db_session: Any = None,
        user_id: str | None = None,
        allowed_endpoints: frozenset[str] | None = None,
        allowed_tools: frozenset[str] | None = None,
        prompt_suffix: str = "",
        rule_hints: dict[str, str] | None = None,
        employee_id: str | None = None,
        web_search_enabled: bool = False,
        search_domain_prefix: str = "",
        search_public_hint: str = "",
        _multiturn_context: dict | None = None,
    ) -> AnalysisPlan:
        """Generate an analysis plan from a structured intent.

        Retries the full LLM call + parse cycle on JSON parsing failures.

        Args:
            allowed_endpoints: 端点白名单 frozenset（来自 EmployeeProfile），硬过滤。
            allowed_tools: 工具白名单 frozenset（来自 EmployeeProfile），硬过滤。
            prompt_suffix: 员工规划层提示后缀。
            rule_hints: 员工对 ``PLANNING_RULE_HINTS`` 的覆写（P3.2）。
                None / 空 dict → 全部走默认。详见 ``resolve_rule_hint``。
            employee_id: 员工 ID，用于模板匹配。
            web_search_enabled: 是否启用联网搜索（开关驱动，非 LLM 自主判断）。
            search_domain_prefix: 搜索 query 自动追加的领域前缀。
            search_public_hint: 员工公开领域关键词提示，用于搜索 query 规划（可选）。
        """
        # 确定合法工具集
        if allowed_tools is not None:
            valid_tools = get_valid_tool_ids(allowed_tools)
        elif available_tools:
            valid_tools = set(available_tools.keys())
        else:
            valid_tools = get_valid_tool_ids()

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
                    if web_search_enabled and search_domain_prefix:
                        bypassed = self._inject_search_tasks(bypassed, intent, search_domain_prefix, search_public_hint)
                    logger.info("Template bypass: employee=%s, tasks=%d", employee_id, len(bypassed.tasks))
                    return bypassed
            except Exception as e:
                logger.warning("Template bypass failed, fallback to LLM: %s", e)

        # Phase-level span around the LLM-driven path. Template-bypass
        # (above) doesn't allocate a planning span — its work is purely
        # deterministic JSON loading. Inside this block we'll emit nested
        # spans for multi-round (skeleton/section/stitch) or for the
        # single-round LLM call.
        intent_preview = (intent.get("raw_query") or "")[:80]
        async with trace_span(
            "phase", "planning",
            task_name="规划阶段",
            phase="planning",
            input={
                "complexity": complexity,
                "employee_id": employee_id,
                "raw_query": intent_preview,
            },
        ) as phase_out:
            # Multi-round planning is the default for full_report. On any failure
            # (timeout / parse / validation) we fall through to the single-round
            # path below — the user always gets a plan. The triggering error is
            # captured so the fallback gets recorded in the resulting plan's
            # revision_log (graph layer turns it into a DegradationEvent).
            multi_round_fallback_error: Exception | None = None
            if complexity == "full_report":
                try:
                    plan = await self._generate_plan_multiround(
                        intent, valid_tools, valid_endpoints, complexity,
                        rule_hints=rule_hints,
                        prompt_suffix=prompt_suffix,
                        _multiturn_context=_multiturn_context,
                    )
                    if web_search_enabled and search_domain_prefix:
                        plan = self._inject_search_tasks(plan, intent, search_domain_prefix, search_public_hint)
                    phase_out["mode"] = "multi_round"
                    phase_out["tasks"] = len(plan.tasks)
                    return plan
                except (PlanningError, asyncio.TimeoutError) as e:
                    logger.warning(
                        "[planning] multi-round failed, fallback to single-round: %s", e,
                    )
                    multi_round_fallback_error = e
                except Exception as e:
                    logger.exception(
                        "[planning] multi-round unexpected error, fallback to single-round: %s", e,
                    )
                    multi_round_fallback_error = e

            # Template hint: 优先 JSON 模板骨架，其次查 DB 历史模板
            if ENABLE_TEMPLATE_HINT:
                template_hint = await self._fetch_template_hint(intent, db_session, user_id, employee_id, complexity)
            else:
                template_hint = ""

            # Agent skills hint: inject enabled SKILL.md workflow instructions
            agent_skills_hint = await self._fetch_agent_skills_hint(db_session)

            prompt = self._build_prompt(
                intent, complexity, db_session, user_id,
                available_tools=available_tools,
                allowed_endpoints=allowed_endpoints,
                allowed_tools=allowed_tools,
                prompt_suffix=prompt_suffix,
                rule_hints=rule_hints,
                template_hint=template_hint,
                agent_skills_hint=agent_skills_hint,
                multiturn_context=_multiturn_context,
            )

            # Use per-complexity timeout; fall back to constructor default only when
            # the complexity-specific value doesn't exist.
            effective_timeout = _PLANNING_TIMEOUT_BY_COMPLEXITY.get(
                complexity, self.llm_timeout
            )

            phase_out["mode"] = (
                "single_round_fallback" if multi_round_fallback_error else "single_round"
            )

            async with trace_span(
                "planning_single_round", "planning.single_round",
                task_name="规划-单轮 LLM",
                phase="planning",
                input={
                    "complexity": complexity,
                    "timeout_s": effective_timeout,
                    "max_retries": self.max_retries,
                    "prompt_chars": len(prompt),
                },
            ) as sr_out:
                last_error: Exception | None = None
                timeout_attempts = 0
                for attempt in range(self.max_retries):
                    if attempt > 0:
                        await asyncio.sleep(1.0 * (2 ** (attempt - 1)))

                    try:
                        raw_output = await asyncio.wait_for(
                            self._invoke_llm(prompt),
                            timeout=effective_timeout,
                        )
                        plan_dict = parse_planning_llm_output(raw_output)
                        mt_turn = (_multiturn_context or {}).get("turn_index", 0)
                        plan = self._build_plan(plan_dict, complexity, intent, turn_index=mt_turn)
                        plan = self._validate_tasks(plan, valid_tools, valid_endpoints, complexity)
                        if multi_round_fallback_error is not None:
                            plan.revision_log.append({
                                "phase": "multi_round_fallback",
                                "ts": int(time.time()),
                                "error_type": type(multi_round_fallback_error).__name__,
                                "error": str(multi_round_fallback_error),
                            })
                        if web_search_enabled and search_domain_prefix:
                            plan = self._inject_search_tasks(plan, intent, search_domain_prefix, search_public_hint)
                        sr_out["attempts"] = attempt + 1
                        sr_out["tasks"] = len(plan.tasks)
                        phase_out["tasks"] = len(plan.tasks)
                        return plan
                    except asyncio.TimeoutError as e:
                        last_error = e
                        timeout_attempts += 1
                        logger.warning(
                            "Planning LLM timeout (attempt %d/%d, complexity=%s, timeout=%.0fs)",
                            attempt + 1, self.max_retries, complexity, effective_timeout,
                        )
                        # Timeout is a capacity/network issue; a single retry is enough.
                        # Retrying 3× would block the user for 3×timeout seconds.
                        if timeout_attempts >= 2:
                            break
                    except PlanningError as e:
                        last_error = e
                        logger.warning("Planning parse error (attempt %d/%d): %s", attempt + 1, self.max_retries, e)
                    except Exception as e:
                        last_error = e
                        logger.warning("Planning error (attempt %d/%d): %s", attempt + 1, self.max_retries, e)

                raise PlanningError(
                    f"规划失败: LLM 调用在 {self.max_retries} 次尝试后仍然失败: {last_error}"
                )

    # ── Multi-round planning (full_report) ────────────────────
    # See SKELETON_PROMPT / SECTION_PROMPT above. Flow:
    #   1. _call_skeleton_llm  → small prompt, ~60s timeout, returns sections
    #   2. _call_section_llm   → N parallel small prompts, each ~60s
    #   3. _stitch_plan        → deterministic merge + append global tasks

    async def _generate_plan_multiround(
        self,
        intent: dict[str, Any],
        valid_tools: set[str],
        valid_endpoints: set[str],
        complexity: str,
        rule_hints: dict[str, str] | None = None,
        prompt_suffix: str = "",
        _multiturn_context: dict | None = None,
    ) -> AnalysisPlan:
        """Two-round planner: skeleton → parallel section fill → stitch."""
        t0 = time.monotonic()
        skeleton = await self._call_skeleton_llm(intent)
        t_skel = time.monotonic() - t0

        if not skeleton.sections:
            raise PlanningError("multi-round: skeleton returned 0 sections")
        if len(skeleton.sections) > 8:
            raise PlanningError(
                f"multi-round: skeleton returned {len(skeleton.sections)} sections (cap=8)"
            )

        sem = asyncio.Semaphore(_PLANNING_SECTION_PARALLELISM)

        async def _try_section(sec, error_feedback=None):
            """调用 section LLM + 预验证，返回 (tasks, feedback_or_none)。

            - 正常无问题：返回 (tasks, None)
            - 有验证问题：返回 (tasks, error_feedback_str) — 调用方应 retry
            - TimeoutError/PlanningError：向上传播给 _fill_one 的系统级重试
            """
            tasks = await self._call_section_llm(
                intent, sec, valid_tools, valid_endpoints,
                rule_hints=rule_hints,
                prompt_suffix=prompt_suffix,
                error_feedback=error_feedback,
            )

            issues = self._validate_section_tasks(
                tasks, valid_tools, valid_endpoints,
            )
            if not issues:
                return tasks, None

            # 构造错误反馈（最多 5 条，防止 prompt 膨胀）
            lines = ["上一轮规划任务因以下问题被拒绝："]
            for issue in issues[:5]:
                lines.append(f"  - {issue['task_id']}: {issue['reason']}")
            lines.append("请重新规划本章节，修正上述问题。")
            return tasks, "\n".join(lines)

        async def _fill_one(sec):
            async with sem:
                # ── 首次尝试 ──
                try:
                    tasks, feedback = await _try_section(sec, None)
                except (asyncio.TimeoutError, PlanningError) as e:
                    logger.warning(
                        "[planning-multiround] section %s first attempt failed: %s",
                        sec.section_id, e,
                    )
                    # 系统级盲重试（保留现有行为）
                    try:
                        return await self._call_section_llm(
                            intent, sec, valid_tools, valid_endpoints,
                            rule_hints=rule_hints,
                            prompt_suffix=prompt_suffix,
                        )
                    except Exception as e2:
                        logger.warning(
                            "[planning-multiround] section %s retry failed: %s",
                            sec.section_id, e2,
                        )
                        return e2

                # ── 验证级重试（带错误上下文） ──
                if feedback:
                    logger.info(
                        "[planning-multiround] section %s has validation issues, "
                        "retrying with feedback",
                        sec.section_id,
                    )
                    try:
                        tasks2, _feedback2 = await _try_section(sec, feedback)
                        return tasks2  # 二次结果直接采纳
                    except (asyncio.TimeoutError, PlanningError) as e:
                        logger.warning(
                            "[planning-multiround] section %s feedback retry "
                            "failed: %s, using first-attempt result",
                            sec.section_id, e,
                        )
                        return tasks  # 回退到首次结果

                return tasks

        t1 = time.monotonic()
        results = await asyncio.gather(*[_fill_one(s) for s in skeleton.sections])
        t_sec = time.monotonic() - t1

        async with trace_span(
            "planning_stitch", "planning.stitch",
            task_name="规划-合并",
            phase="planning",
            input={
                "sections_total": len(skeleton.sections),
                "needs_attribution": skeleton.needs_attribution,
                "output_formats": list(skeleton.output_formats),
            },
        ) as stitch_out:
            mt_turn = (_multiturn_context or {}).get("turn_index", 0)
            plan = self._stitch_plan(intent, skeleton, results, turn_index=mt_turn)
            plan = self._validate_tasks(plan, valid_tools, valid_endpoints, complexity)

            # Surface stitch result for the trace pane: kept vs failed
            # sections + the global tasks that got appended.
            stitch_log = next(
                (e for e in plan.revision_log
                 if e.get("phase") == "multi_round_stitch"),
                {},
            )
            stitch_out["sections_kept"] = stitch_log.get("sections_kept")
            stitch_out["failed_sections"] = stitch_log.get("failed_sections", [])
            stitch_out["tasks_total"] = len(plan.tasks)
            stitch_out["global_tasks"] = [
                t.task_id for t in plan.tasks
                if t.task_id.startswith("G_")
            ]

        n_failed = sum(1 for r in results if isinstance(r, BaseException))
        logger.info(
            "[planning-multiround] sections=%d skeleton=%.2fs sections_total=%.2fs "
            "failed=%d total=%.2fs tasks=%d",
            len(skeleton.sections), t_skel, t_sec, n_failed,
            time.monotonic() - t0, len(plan.tasks),
        )
        return plan

    async def _call_skeleton_llm(self, intent: dict[str, Any]) -> "PlanSkeleton":
        """Round 1: produce section structure only (no concrete tasks)."""
        from backend.models.schemas import PlanSkeleton
        from backend.agent.api_registry import DOMAIN_INDEX

        domain_lines = [
            f"- {code}: {info.name} — {info.desc}"
            for code, info in DOMAIN_INDEX.items()
        ]
        domain_index_str = "\n".join(domain_lines)

        output_formats = self._extract_output_formats(intent)
        output_formats_hint = (
            f"用户期望格式: {', '.join(output_formats)}（决定 report_gen 工具种类，"
            f"由系统在合并阶段补任务，本阶段无需生成）"
        )

        prompt = SKELETON_PROMPT.format(
            intent_json=json.dumps(intent, ensure_ascii=False, indent=2, default=str),
            domain_index=domain_index_str,
            output_formats_hint=output_formats_hint,
        )

        async with trace_span(
            "planning_skeleton", "planning.skeleton",
            task_name="规划-章节大纲",
            phase="planning",
            input={
                "timeout_s": _PLANNING_SKELETON_TIMEOUT,
                "prompt_chars": len(prompt),
                "expected_formats": output_formats,
            },
        ) as out:
            raw = await asyncio.wait_for(
                self._invoke_llm(prompt),
                timeout=_PLANNING_SKELETON_TIMEOUT,
            )
            parsed = parse_planning_llm_output(raw)
            # If LLM forgot output_formats, take it from intent.
            parsed.setdefault("output_formats", output_formats)
            skel = PlanSkeleton(**parsed)
            self._enrich_section_endpoints(skel)
            out["sections"] = [s.section_id for s in skel.sections]
            out["needs_attribution"] = skel.needs_attribution
            out["output_formats"] = list(skel.output_formats)
            return skel

    def _enrich_section_endpoints(self, skel: "PlanSkeleton") -> None:
        """Fill endpoint_hints from domain_hint if the LLM left it empty."""
        from backend.agent.api_registry import BY_DOMAIN
        for sec in skel.sections:
            if sec.endpoint_hints:
                continue
            if not sec.domain_hint:
                continue
            eps = BY_DOMAIN.get(sec.domain_hint, [])
            sec.endpoint_hints = [ep.name for ep in eps[:8]]

    def _extract_output_formats(self, intent: dict[str, Any]) -> list[str]:
        """Pull output_format slot out of intent; default to ['HTML']."""
        slots = intent.get("slots", {}) if isinstance(intent.get("slots"), dict) else {}
        fmt_slot = slots.get("output_format", {}) if isinstance(slots, dict) else {}
        raw = fmt_slot.get("value") if isinstance(fmt_slot, dict) else None
        if raw is None:
            raw = intent.get("output_format")
        items = raw if isinstance(raw, list) else [raw] if raw else []
        out = [str(i).strip().upper() for i in items if i]
        return list(dict.fromkeys(out)) or ["HTML"]

    async def _call_section_llm(
        self,
        intent: dict[str, Any],
        section: "PlanSection",
        valid_tools: set[str],
        valid_endpoints: set[str],
        rule_hints: dict[str, str] | None = None,
        prompt_suffix: str = "",
        error_feedback: str | None = None,
    ) -> list[TaskItem]:
        """Round 2 (one section): produce concrete data_fetch/analysis/viz tasks."""
        # Only feed endpoints relevant to this section. If domain reverse-lookup
        # produced nothing (e.g. LLM gave a bogus domain_hint), fall back to a
        # bounded slice of valid_endpoints so the prompt still has *some* options.
        section_eps = frozenset(section.endpoint_hints) & valid_endpoints
        if not section_eps:
            section_eps = frozenset(list(valid_endpoints)[:15])
        section_endpoints_desc = get_endpoints_description(
            allowed_endpoints=section_eps,
        )

        if valid_tools:
            tools_desc = get_tools_description(allowed_tools=frozenset(valid_tools))
        else:
            tools_desc = get_tools_description()

        # P3.2: thread employee Cookbook into section prompts. The
        # single-round prompt has wrapped this under "【意图结构化提示】"
        # — sections aren't structured-hint emitters, so we render a
        # standalone "【员工专属规划提示（Cookbook）】" block instead.
        cookbook_block = (
            f"\n【员工专属规划提示（Cookbook）】\n{prompt_suffix}\n"
            if prompt_suffix else ""
        )

        # ── Tier 1.1: 注入具体时间参数候选值 ──
        time_hints = _extract_time_hints(intent)
        time_hints_block = ""
        if time_hints:
            parts = [f"  {k} = {v}" for k, v in sorted(time_hints.items())]
            time_hints_block = (
                "【时间参数具体值】（从用户 time_range 推导，data_fetch 任务必须使用）\n"
                + "\n".join(parts) + "\n"
            )

        # ── Tier 1.2: 必填参数集中警告 ──
        required_summary = []
        for ep_name in sorted(section_eps):
            ep = get_endpoint(ep_name)
            if ep and ep.required:
                required_summary.append(
                    f"  - {ep_name} 必填: {', '.join(ep.required)}"
                )
        required_warning = ""
        if required_summary:
            required_warning = (
                "【端点必填参数总览】（⚠️ 每个 data_fetch 任务必须在 params 中包含下列参数）\n"
                + "\n".join(required_summary) + "\n"
            )

        # ── Tier 2: 错误反馈（retry 时非空） ──
        error_feedback_block = ""
        if error_feedback:
            error_feedback_block = (
                "\n【上一轮规划错误，请修正】\n" + error_feedback + "\n"
            )

        prompt = SECTION_PROMPT.format(
            section_id=section.section_id,
            section_name=section.name,
            section_description=section.description,
            focus_metrics=", ".join(section.focus_metrics) or "（未指定）",
            expected_task_count=section.expected_task_count,
            intent_json=json.dumps(intent, ensure_ascii=False, default=str),
            section_endpoints_desc=section_endpoints_desc,
            tools_description=tools_desc,
            time_param_rules=resolve_rule_hint("time_param", rule_hints),
            cargo_selection_rules=resolve_rule_hint("cargo_selection", rule_hints),
            employee_cookbook=cookbook_block,
            time_hints=time_hints_block,
            required_warning=required_warning,
            error_feedback=error_feedback_block,
        )

        async with trace_span(
            "planning_section",
            f"planning.section.{section.section_id}",
            task_name=f"规划-章节: {section.name}",
            phase="planning",
            input={
                "section_id": section.section_id,
                "section_name": section.name,
                "endpoint_count": len(section_eps),
                "expected_task_count": section.expected_task_count,
                "timeout_s": _PLANNING_SECTION_TIMEOUT,
                "prompt_chars": len(prompt),
            },
        ) as section_out:
            raw = await asyncio.wait_for(
                self._invoke_llm(prompt),
                timeout=_PLANNING_SECTION_TIMEOUT,
            )
            parsed = parse_planning_llm_output(raw)
            section_out["raw_tasks"] = len(parsed.get("tasks", []))

        tasks: list[TaskItem] = []
        for idx, t_dict in enumerate(parsed.get("tasks", []), start=1):
            tid = t_dict.get("task_id") or f"{section.section_id}.T{idx}"
            if not tid.startswith(f"{section.section_id}."):
                # LLM ignored the prefix rule; rewrite to keep IDs unique
                tid = f"{section.section_id}.{tid}"
            tasks.append(TaskItem(
                task_id=tid,
                type=t_dict.get("type", "data_fetch"),
                name=t_dict.get("name", ""),
                description=t_dict.get("description", ""),
                depends_on=list(t_dict.get("depends_on", [])),
                tool=t_dict.get("tool", ""),
                params=dict(t_dict.get("params", {})),
                estimated_seconds=int(t_dict.get("estimated_seconds", 10)),
                intent=t_dict.get("intent", ""),
            ))
        return tasks

    def _stitch_plan(
        self,
        intent: dict[str, Any],
        skeleton: "PlanSkeleton",
        section_results: list,
        turn_index: int = 0,
    ) -> AnalysisPlan:
        """Deterministically merge per-section tasks and append global tasks.

        - Tolerates partial section failure up to PLANNING_SECTION_FAILURE_RATIO.
        - Appends G_ATTR (if needed), G_SUM, and G_REPORT_<fmt> tasks with
          dependencies wired from collected section task IDs. No LLM call.
        """
        tasks: list[TaskItem] = []
        failed: list[tuple[str, str]] = []
        kept_sections: list = []
        for sec, result in zip(skeleton.sections, section_results):
            if isinstance(result, BaseException):
                failed.append((sec.section_id, repr(result)))
                continue
            if not result:
                failed.append((sec.section_id, "empty tasks"))
                continue
            tasks.extend(result)
            kept_sections.append(sec)

        n_total = len(skeleton.sections)
        max_failures = max(1, int(n_total * _PLANNING_SECTION_FAILURE_RATIO))
        if len(failed) > max_failures:
            raise PlanningError(
                f"multi-round: too many sections failed "
                f"({len(failed)}/{n_total}, cap={max_failures}): {failed}"
            )

        analysis_ids   = [t.task_id for t in tasks if t.type == "analysis"]
        viz_ids        = [t.task_id for t in tasks if t.type == "visualization"]
        data_fetch_ids = [t.task_id for t in tasks if t.type == "data_fetch"]

        if skeleton.needs_attribution and data_fetch_ids:
            tasks.append(TaskItem(
                task_id="G_ATTR",
                type="analysis",
                name="归因分析",
                description="基于上游数据分析核心驱动因素",
                depends_on=data_fetch_ids[:5],
                tool="tool_attribution",
                params={},
                intent=f"分析{skeleton.title or '本报告'}的核心驱动因素",
                estimated_seconds=45,
            ))
            analysis_ids.append("G_ATTR")

        if analysis_ids:
            tasks.append(TaskItem(
                task_id="G_SUM",
                type="summary",
                name="综合分析汇总",
                description="汇总各章节分析结论",
                depends_on=analysis_ids,
                tool="tool_summary_gen",
                params={"intent": skeleton.analysis_goal},
                intent=skeleton.analysis_goal,
                estimated_seconds=20,
            ))

        fmt_tool_map = {
            "HTML": "tool_report_html",
            "DOCX": "tool_report_docx",
            "WORD": "tool_report_docx",
            "PPTX": "tool_report_pptx",
            "PPT":  "tool_report_pptx",
        }
        report_deps = list(viz_ids)
        if analysis_ids:
            report_deps.append("G_SUM")
        for fmt in skeleton.output_formats:
            tool = fmt_tool_map.get(fmt, "tool_report_html")
            tasks.append(TaskItem(
                task_id=f"G_REPORT_{fmt}",
                type="report_gen",
                name=f"生成{fmt}报告",
                description=f"输出 {fmt} 格式报告",
                depends_on=report_deps,
                tool=tool,
                params={
                    "intent": skeleton.analysis_goal,
                    "report_structure": {
                        "sections": [{"name": s.name} for s in kept_sections],
                    },
                },
                intent=skeleton.analysis_goal,
                estimated_seconds=30,
            ))

        # Multi-turn: prefix task_ids with R{turn_index}_
        _add_task_id_prefix(tasks, turn_index)

        plan = AnalysisPlan(
            plan_id=str(uuid4()),
            version=1,
            title=skeleton.title or "分析方案",
            analysis_goal=skeleton.analysis_goal,
            estimated_duration=sum(t.estimated_seconds for t in tasks),
            tasks=_break_cycles(tasks),
            report_structure={
                "sections": [{"name": s.name} for s in kept_sections],
            },
            turn_index=turn_index,
            revision_log=[{
                "phase": "multi_round_stitch",
                "ts": int(time.time()),
                "sections_total": n_total,
                "sections_kept": len(kept_sections),
                "failed_sections": failed,
            }],
        )
        return plan

    def _get_complexity(self, intent: dict) -> str:
        """Extract output_complexity from intent."""
        if "output_complexity" in intent:
            return intent["output_complexity"]
        # From slots dict
        slots = intent.get("slots", {})
        if isinstance(slots, dict):
            comp_slot = slots.get("output_complexity", {})
            if isinstance(comp_slot, dict):
                val = comp_slot.get("value")
                if val and val in COMPLEXITY_RULES:
                    return val
        return "simple_table"

    def _build_prompt(
        self,
        intent: dict,
        complexity: str,
        db_session: Any = None,
        user_id: str | None = None,
        available_tools: dict[str, Any] | None = None,
        allowed_endpoints: frozenset[str] | None = None,
        allowed_tools: frozenset[str] | None = None,
        prompt_suffix: str = "",
        rule_hints: dict[str, str] | None = None,
        template_hint: str = "",
        agent_skills_hint: str = "",
        multiturn_context: dict | None = None,  # PR-1: multi-turn context
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

        # Use available_tools descriptions when provided, else default registry
        if available_tools:
            lines = []
            for tool_id, info in available_tools.items():
                desc = info.get("description", "")
                inp = info.get("input", "")
                out = info.get("output", "")
                lines.append(f"- {tool_id}: {desc}")
                if inp or out:
                    lines.append(f"  输入: {inp} → 输出: {out}")
            tools_desc = "\n".join(lines)
        elif allowed_tools is not None:
            tools_desc = get_tools_description(allowed_tools=allowed_tools)
        else:
            tools_desc = get_tools_description()

        endpoints_desc = get_endpoints_description(
            domain_hint, time_hint, granularity_hint,
            allowed_endpoints=allowed_endpoints,
                )

        # Report hint_hint = ""
        # Template lookup is deferred to integration (requires async DB)

        # Report hint: 5层链路规范
        report_hint = ""
        if complexity == "full_report":
            slots_inner = intent.get("slots", {})

            def _normalize_formats(raw: Any) -> list[str]:
                if raw is None:
                    return []
                items = raw if isinstance(raw, list) else [raw]
                out: list[str] = []
                for item in items:
                    if item is None:
                        continue
                    s = str(item).strip().upper()
                    if s:
                        out.append(s)
                return list(dict.fromkeys(out))  # preserve order, dedupe

            raw_formats: list[str] = []
            if isinstance(slots_inner, dict):
                fmt_slot = slots_inner.get("output_format", {})
                if isinstance(fmt_slot, dict):
                    raw_formats = _normalize_formats(fmt_slot.get("value"))
            if not raw_formats:
                raw_formats = _normalize_formats(intent.get("output_format"))
            output_formats = raw_formats or ["HTML"]

            format_tool_map = {
                "HTML": "tool_report_html",
                "DOCX": "tool_report_docx",
                "WORD": "tool_report_docx",
                "PPTX": "tool_report_pptx",
                "PPT": "tool_report_pptx",
            }
            report_tools = [
                (fmt, format_tool_map.get(fmt, "tool_report_html"))
                for fmt in output_formats
            ]

            attr_slot = slots_inner.get("attribution_needed", {}) if isinstance(slots_inner, dict) else {}
            attr_needed = attr_slot.get("value", True) if isinstance(attr_slot, dict) else True
            attr_note = "" if attr_needed else "\n  → attribution_needed=false，可省略 tool_attribution 任务"

            if len(report_tools) == 1:
                fmt, tool = report_tools[0]
                layer5_spec = (
                    f"  Layer5 报告层（1，必须最后）: {tool}\n"
                    f"    → depends_on 所有可视化层 + 汇总层任务\n"
                    f"    → estimated_seconds: 60\n"
                    f"    → params 包含 intent（报告意图）+ report_metadata: {{title, author, date}}"
                )
                format_display = fmt
            else:
                format_display = " / ".join(fmt for fmt, _ in report_tools)
                lines = [
                    f"  Layer5 报告层（共 {len(report_tools)} 个任务，每种格式 1 个，必须最后）:"
                ]
                for fmt, tool in report_tools:
                    lines.append(
                        f"    • {tool}（{fmt}）→ depends_on 所有可视化层 + 汇总层任务；"
                        f"estimated_seconds: 30；params 包含 intent + report_metadata: {{title, author, date}}"
                    )
                layer5_spec = "\n".join(lines)

            report_hint = (
                f"【full_report 报告生成规范】\n"
                f"报告格式: {format_display}\n\n"
                f"必须按5层链路组织 tasks：\n"
                f"  Layer1 数据层（≥4）: tool_api_fetch × N（主KPI + 趋势序列 + 结构分布 + 对比基线）\n"
                f"  Layer2 分析层（≥2）: tool_desc_analysis + tool_attribution{attr_note}\n"
                f"    → 每个分析任务 depends_on 对应的数据层任务\n"
                f"  Layer3 可视化层（≥3）: tool_chart_bar / tool_chart_line / tool_chart_waterfall 组合\n"
                f"    → 每图 depends_on 1-2个数据层任务\n"
                f"  Layer4 汇总层（1）: tool_summary_gen，depends_on 所有分析层任务\n"
                f"    → params 只写 intent，禁止写 summary_style / topic / domain\n"
                f"{layer5_spec}\n\n"
                f"report_structure 必须填充，sections 只写章节名，不写 task_refs（执行时自动关联）:\n"
                f'  {{"sections": [{{"name": "章节名"}}, ...]}}\n'
                f"建议章节：一、概览 | 二、趋势分析 | 三、结构分析 | 四、归因分析 | 五、结论建议\n\n"
                f"报告工具 params 禁止出现：summary_style / topic / domain / template_id / task_refs"
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

        # Multi-turn context block (PR-2: Layer 3 — enhanced)
        multi_turn_text = ""
        if multiturn_context:
            latest = multiturn_context.get("latest_summary", {})
            findings = multiturn_context.get("all_key_findings", [])[:5]
            prev_endpoints = multiturn_context.get("prev_data_endpoints", [])
            turn_idx = multiturn_context.get("turn_index", 0)
            plan_history = multiturn_context.get("plan_history", [])
            completed_summary = _build_completed_plan_summary(plan_history)

            multi_turn_text = (
                f"【多轮分析上下文 — 必读】\n"
                f"当前是第 {turn_idx} 轮分析（延续上轮）。前轮分析已完成：\n"
                f"- 主题：{latest.get('plan_title', '')[:150]}\n"
                f"- 已完成 {latest.get('completed_count', 0)}/{latest.get('task_count', 0)} 个任务\n"
                f"- 关键发现：{'；'.join(f[:_MAX_FINDING_LEN] for f in findings) if findings else '无'}\n"
                f"- 已调用的数据端点：{', '.join(prev_endpoints) if prev_endpoints else '无'}\n"
                f"\n【前轮已完成任务列表 — 绝对不要重复规划】\n{completed_summary}\n"
                f"\n【本轮规划约束】\n"
                f"- 以下端点数据已经获取，可直接复用（不需要重复 data_fetch）：{', '.join(prev_endpoints)}\n"
                f"- task_id 请以 R{turn_idx}_ 为前缀\n"
                f"- 仅规划本轮新增任务，不要重复已有任务\n"
            )

        result = PLANNING_PROMPT.format(
            multiturn_context=multi_turn_text,
            intent_json=intent_json,
            tools_description=tools_desc,
            endpoints_description=endpoints_desc,
            agent_skills_hint=agent_skills_hint,
            structured_hints=structured_hints,
            template_hint=template_hint,
            complexity=complexity,
            report_hint=report_hint,
            minimization_rules=resolve_rule_hint("minimization", rule_hints),
            time_param_rules=resolve_rule_hint("time_param", rule_hints),
            cargo_selection_rules=resolve_rule_hint("cargo_selection", rule_hints),
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

    async def _fetch_agent_skills_hint(self, db_session: Any) -> str:
        """Inject enabled SKILL.md workflow instructions into the planner prompt."""
        if db_session is None:
            return ""
        try:
            from backend.memory.admin_store import list_enabled_agent_skills
            skills = await list_enabled_agent_skills(db_session)
            if not skills:
                return ""
            lines = ["【Agent 技能（工作流指导）】"]
            for s in skills:
                lines.append(f"\n## {s['name']}")
                if s.get("description"):
                    lines.append(s["description"])
                if s.get("content"):
                    lines.append(s["content"])
            return "\n".join(lines) + "\n\n"
        except Exception:
            return ""

    def _build_plan(
        self, plan_dict: dict, complexity: str, intent: dict,
        turn_index: int = 0,
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
                tool=t_dict.get("tool", ""),
                params=t_dict.get("params", {}),
                estimated_seconds=t_dict.get("estimated_seconds", 10),
                intent=t_dict.get("intent", ""),
            ))

        # Multi-turn: prefix task_ids with R{turn_index}_
        _add_task_id_prefix(tasks, turn_index)

        report_structure = _sanitize_report_structure(plan_dict.get("report_structure"))

        return AnalysisPlan(
            plan_id=str(uuid4()),
            version=1,
            title=plan_dict.get("title", "分析方案"),
            analysis_goal=plan_dict.get("analysis_goal", ""),
            estimated_duration=plan_dict.get("estimated_duration", sum(t.estimated_seconds for t in tasks)),
            tasks=tasks,
            report_structure=report_structure,
            revision_log=[],
            turn_index=turn_index,
        )

    def _validate_section_tasks(
        self,
        tasks: list[TaskItem],
        valid_tools: set[str],
        valid_endpoints: set[str],
    ) -> list[dict[str, str]]:
        """预验证单个 section 的任务列表。

        在 section 生成任务后、stitch 前调用，检测可修正的问题
        （如缺必填参数），为 retry 提供结构化错误反馈。

        返回被判定为 drop 的任务列表 [{task_id, reason}]。
        注意：此处不执行级联删除，级联逻辑保留在 _validate_tasks 中。
        """
        issues: list[dict[str, str]] = []
        for task in tasks:
            reason = self._task_drop_reason(task, valid_tools, valid_endpoints)
            if reason:
                issues.append({"task_id": task.task_id, "reason": reason})
        return issues

    def _task_drop_reason(
        self,
        task: TaskItem,
        valid_tools: set[str],
        valid_endpoints: set[str],
    ) -> str | None:
        """Return a human-readable drop reason, or None to keep the task.

        Side effect: M-code endpoints get rewritten in-place to their canonical
        form when resolvable.
        """
        if task.tool and task.tool not in valid_tools:
            return f"hallucinated tool '{task.tool}'"

        endpoint_id = task.params.get("endpoint_id")
        if endpoint_id and endpoint_id not in valid_endpoints:
            resolved = resolve_endpoint_id(endpoint_id)
            if resolved and resolved in valid_endpoints:
                logger.info(
                    "Resolved M-code '%s' → '%s' for task %s",
                    endpoint_id, resolved, task.task_id,
                )
                task.params["endpoint_id"] = resolved
                endpoint_id = resolved
            else:
                return f"hallucinated endpoint '{endpoint_id}'"

        if task.type == "data_fetch" and endpoint_id:
            ep = get_endpoint(endpoint_id)
            if ep and ep.required:
                query_params = {k: v for k, v in task.params.items() if k != "endpoint_id"}
                missing = [p for p in ep.required if p not in query_params]
                if missing:
                    return f"endpoint {endpoint_id} missing required params: {', '.join(missing)}"

        return None

    def _inject_search_tasks(
        self,
        plan: AnalysisPlan,
        intent: dict[str, Any],
        search_domain_prefix: str,
        search_public_hint: str = "",
    ) -> AnalysisPlan:
        """Deterministically inject web-search task(s) into the plan.

        This is the SINGLE point where search tasks enter any plan. When the
        user enables web search, we guarantee at least one search task — never
        left to LLM discretion. The query is built from plan metadata and the
        employee's search domain prefix.

        Strategy:
        1. Remove any LLM-generated search tasks (shouldn't exist, but clean slate).
        2. Build a query from plan title + domain prefix.
        3. Insert a single G_SEARCH task after the last data_fetch task.
        """
        if not search_domain_prefix:
            return plan

        # ── Remove any existing search tasks (idempotent clean-up) ──
        plan.tasks = [t for t in plan.tasks if t.type != "search"]

        # ── Derive search query ──
        # 优先用用户原始问题（raw_query）作为搜索词，plan title 偏技术化不适合搜索
        # 只用第一个领域关键词（公司名）作为 scope，避免关键词过多导致无结果
        scope = search_domain_prefix.split()[0]
        search_text = intent.get("raw_query", "") or plan.title or "数据分析"
        query = f"{scope} {search_text}"
        # Truncate to a reasonable keyword length (avoid overly long queries)
        if len(query) > 200:
            query = query[:200]

        # ── Build the search task ──
        search_task = TaskItem(
            task_id="G_SEARCH",
            type="search",
            name=f"联网检索：{scope}相关行业信息",
            description="互联网检索分析主题相关外部信息，为分析提供宏观背景和行业参考",
            depends_on=[],
            tool="tool_web_search",
            params={
                "query": query,
                "__search_domain_prefix__": search_domain_prefix,
                "__search_public_hint__": search_public_hint,
                "__raw_query__": search_text,
                "__task_intent__": intent.get("purpose", "") or "",
            },
            intent=(
                f"了解{search_text[:50]}的行业背景、政策环境和市场趋势，"
                f"补充外部信息以增强分析的全面性"
            ),
            estimated_seconds=45,
        )

        # ── Insert after the last data_fetch task, or at head ──
        insert_at = 0
        for i, t in enumerate(plan.tasks):
            if t.type == "data_fetch":
                insert_at = i + 1
        plan.tasks.insert(insert_at, search_task)

        plan.estimated_duration += search_task.estimated_seconds

        logger.info(
            "Injected search task G_SEARCH after %d data_fetch tasks, query=%s",
            sum(1 for t in plan.tasks[:insert_at] if t.type == "data_fetch"),
            query[:80],
        )
        return plan

    def _validate_tasks(
        self,
        plan: AnalysisPlan,
        valid_tools: set[str],
        valid_endpoints: set[str],
        complexity: str,
    ) -> AnalysisPlan:
        """Validate tasks: filter hallucinated tools/endpoints, cap count, break cycles.

        Cascade behaviour: when a task is dropped, every downstream task that
        transitively depends on it is also dropped (with reason
        ``"upstream dropped: <ids>"``). Empty result sets that violate the
        complexity contract raise PlanningError to trigger a regeneration
        attempt — silent degradation here was the source of the
        "T002 orphan visualization" bug class.

        All drops are recorded in ``plan.revision_log`` so downstream layers
        (chat bubble, reflection) can surface them to the user instead of
        them disappearing into log files.
        """
        original_count = len(plan.tasks)
        drop_reasons: dict[str, str] = {}

        # Phase 1 — direct violations
        for task in plan.tasks:
            reason = self._task_drop_reason(task, valid_tools, valid_endpoints)
            if reason:
                drop_reasons[task.task_id] = reason

        # Phase 2 — cascade: any task whose dependency was dropped is also dropped
        changed = True
        while changed:
            changed = False
            for task in plan.tasks:
                if task.task_id in drop_reasons:
                    continue
                broken = [d for d in task.depends_on if d in drop_reasons]
                if broken:
                    drop_reasons[task.task_id] = (
                        f"upstream dropped: {','.join(broken)}"
                    )
                    changed = True

        # Phase 3 — apply
        kept = [t for t in plan.tasks if t.task_id not in drop_reasons]

        if drop_reasons:
            logger.warning(
                "Plan validation dropped %d/%d tasks: %s",
                len(drop_reasons), original_count, drop_reasons,
            )

        # Phase 4 — task count soft warning (was: hard cap; now: advisory only)
        _, _, max_soft = get_task_count_hint(complexity)
        if len(kept) > max_soft:
            plan.revision_log.append({
                "phase": "validation_warning",
                "ts": int(time.time()),
                "message": (
                    f"{complexity} 任务数 {len(kept)} 超过软建议上限 {max_soft}, "
                    f"未截断, 仅记录"
                ),
            })
            logger.info(
                "Task count %d exceeds soft hint %d for %s (not truncated)",
                len(kept), max_soft, complexity,
            )

        # Phase 5 — record structured drops on the plan
        if drop_reasons:
            plan.revision_log.append({
                "phase": "validation",
                "ts": int(time.time()),
                "original_count": original_count,
                "kept_count": len(kept),
                "dropped": drop_reasons,
            })

        # Phase 6 — clean stale dep references on kept tasks
        valid_task_ids = {t.task_id for t in kept}
        for task in kept:
            task.depends_on = [d for d in task.depends_on if d in valid_task_ids]

        plan.tasks = kept

        # Phase 7 — complexity hard-constraint enforcement
        # Raise PlanningError to trigger regeneration; the surrounding retry
        # loop in generate_plan will catch and retry. After max_retries,
        # surfaces to the user as a planning failure rather than a silently
        # broken plan that crashes during execution.
        self._enforce_complexity_constraints(plan, complexity)

        # Phase 8 — break cycles
        plan.tasks = _break_cycles(plan.tasks)

        return plan

    def _enforce_complexity_constraints(
        self,
        plan: AnalysisPlan,
        complexity: str,
    ) -> None:
        """Enforce complexity invariants derived from _complexity_rules.

        Three hard checks (raise PlanningError on violation → trigger retry):
          1. Data source: every complexity needs ≥ 1 fetch tool
             (api_fetch or file_parse).
          2. forbidden_tools: explicit blacklist must be empty.
          3. full_report: ≥ 1 report-file tool required.

        Soft warnings (revision_log, no exception):
          - full_report without charts
          - task-count exceeds max_soft (handled in _validate_tasks Phase 4)
        """
        rule = get_rule(complexity)
        tasks = plan.tasks
        if not tasks:
            raise PlanningError(
                f"规划失败：过滤后没有剩余任务（complexity={complexity}）"
            )

        tools_used = {t.tool for t in tasks if t.tool}

        # 1. Data source check (all levels — including simple_table)
        #    Covers simple_table where forbidden_tools don't include fetch but
        #    we still need ≥ 1 data-source task.
        if not (tools_used & DATA_SOURCE_TOOLS):
            raise PlanningError(
                f"{complexity} 复杂度要求至少 1 个数据获取任务 "
                f"(tool_api_fetch 或 tool_file_parse), 过滤后剩 0 个"
            )

        # 2. forbidden_tools blacklist (single source of truth)
        forbidden_present = tools_used & rule.forbidden_tools
        if forbidden_present:
            raise PlanningError(
                f"{complexity} 复杂度禁止使用: {sorted(forbidden_present)}"
            )

        # 3. full_report requires ≥ 1 report-file tool
        if complexity == "full_report":
            if not (tools_used & REPORT_FILE_TOOLS):
                raise PlanningError(
                    f"full_report 复杂度要求至少 1 个报告文件工具 "
                    f"({sorted(REPORT_FILE_TOOLS)})"
                )

        # Soft warning: full_report without charts
        # Uses CHART_TOOLS from _complexity_rules — no hardcoded drift.
        # int(time.time()) relies on the existing ``import time`` at file top.
        if complexity == "full_report" and not (tools_used & CHART_TOOLS):
            plan.revision_log.append({
                "phase": "validation_warning",
                "ts": int(time.time()),
                "message": "full_report 未生成图表任务, 报告可能仅含文字",
            })

        # Notes:
        # - chart_text no longer requires charts (discussion point #7)
        # - No forbidden_categories check (avoids tool_summary_gen being
        #   accidentally banned due to category="report")
        # - chart_text summary_gen now works correctly

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


_LAYER_ORDER = ["data_fetch", "search", "analysis", "visualization", "report_gen"]

_REPORT_TOOL_TO_FORMAT = {
    "tool_report_html": "HTML",
    "tool_report_docx": "DOCX",
    "tool_report_pptx": "PPTX",
    "tool_report_markdown": "Markdown",
}


def _fmt_duration(seconds: int) -> str:
    if seconds >= 60:
        return f"约 {seconds // 60} 分钟"
    return f"约 {seconds} 秒"


def _summarize_deliverables(grouped: dict[str, list[TaskItem]]) -> str:
    """Produce a short, user-facing description of what the plan delivers."""
    report_tasks = grouped.get("report_gen", [])
    viz_tasks = grouped.get("visualization", [])
    data_tasks = grouped.get("data_fetch", [])

    parts: list[str] = []

    if report_tasks:
        formats: list[str] = []
        for t in report_tasks:
            fmt = _REPORT_TOOL_TO_FORMAT.get(t.tool)
            if fmt and fmt not in formats:
                formats.append(fmt)
        if formats:
            parts.append(
                f"{len(report_tasks)} 份综合报告（{' / '.join(formats)}）"
            )
        else:
            parts.append(f"{len(report_tasks)} 份综合报告")

    if viz_tasks and not report_tasks:
        # If report_gen exists, charts are embedded in the report — don't double-count.
        parts.append(f"{len(viz_tasks)} 张图表")

    if not report_tasks and not viz_tasks and data_tasks:
        parts.append(f"{len(data_tasks)} 份数据查询结果")

    return "；".join(parts) if parts else "分析结果"


def format_plan_as_markdown(plan: AnalysisPlan, auto_confirmed: bool = False, web_search_enabled: bool = False, search_domain_prefix: str = "") -> str:
    """Format an AnalysisPlan as a user-facing **summary** in Markdown.

    The chat bubble is intentionally summary-only — the full interactive
    task list lives in the Inspector's PlanCard. Here we surface:

    1. Deliverables (what will I actually get)
    2. Execution scope by layer (counts + subtotal time)
    3. Total time and action line
    4. Web search toggle status + domain prefix (always visible for diagnostics)

    When `auto_confirmed` is True (simple plans that skip the confirmation
    prompt), the trailing action line is omitted so the frontend renders
    the plan as a read-only summary rather than a blocking card.
    """
    total_seconds = plan.estimated_duration or sum(t.estimated_seconds for t in plan.tasks)

    grouped: dict[str, list[TaskItem]] = {}
    for task in plan.tasks:
        grouped.setdefault(task.type, []).append(task)

    # ── 联网搜索状态（始终显示，用于诊断）──
    search_tasks = [t for t in plan.tasks if t.type == "search"]

    lines: list[str] = [
        f"**分析方案 · v{plan.version}**（预计完成时间：{_fmt_duration(total_seconds)}）",
        "",
        f"**分析目标：** {plan.analysis_goal or plan.title}",
    ]
    if web_search_enabled:
        if not search_domain_prefix:
            lines.append("  **联网搜索:** [异常] 开关已开启但 search_domain_prefix 为空（员工 profile 缺失配置）")
        elif search_tasks:
            lines.append(f"  **联网搜索:** 已开启 (prefix: {search_domain_prefix[:40]}...)，计划中包含 {len(search_tasks)} 个搜索任务")
        else:
            lines.append(f"  **联网搜索:** [异常] 开关已开启 (prefix: {search_domain_prefix[:40]}...) 但未注入搜索任务（检查 _inject_search_tasks 日志）")
    else:
        lines.append("  **联网搜索:** 未开启")
    lines.append("")

    lines.extend([
        "**交付产出**",
        f"- {_summarize_deliverables(grouped)}",
    ])

    # 搜索任务详情（仅当存在搜索任务时展开 query 信息）
    if search_tasks:
        lines.append("")
        lines.append("**联网检索**")
        for t in search_tasks:
            query = (t.params or {}).get("query", "") or t.name
            reason = t.description or "补充外部信息"
            lines.append(f"- 搜索 \"{query}\" — {reason}")

    lines.extend([
        "",
        f"**执行范围**（共 {len(plan.tasks)} 个任务）",
    ])

    # Show layer counts + subtotal time, without listing individual tasks.
    rendered_types: set[str] = set()
    for ttype in _LAYER_ORDER:
        group = grouped.get(ttype)
        if not group:
            continue
        label = TYPE_LABELS.get(ttype, ttype)
        group_seconds = sum(t.estimated_seconds for t in group)
        lines.append(f"- {label} · {len(group)} 个（{_fmt_duration(group_seconds)}）")
        rendered_types.add(ttype)

    for ttype, group in grouped.items():
        if ttype in rendered_types:
            continue
        label = TYPE_LABELS.get(ttype, ttype)
        group_seconds = sum(t.estimated_seconds for t in group)
        lines.append(f"- {label} · {len(group)} 个（{_fmt_duration(group_seconds)}）")

    lines.extend([
        "",
        "_完整任务清单见右侧「计划」面板_",
        "",
        "---",
    ])

    if auto_confirmed:
        lines.append("_自动执行中…_")
    else:
        lines.append("[确认执行] [修改方案] [重新规划]")

    return "\n".join(lines)


def is_simple_plan(plan: AnalysisPlan) -> bool:
    """A plan is "simple" when it can safely auto-execute without user
    confirmation — few tasks, no report generation, no human-in-the-loop
    hints in task metadata.

    Threshold of 3 tasks picked to cover the common "data fetch →
    visualize → describe" pattern while deferring L3 deep reports
    (which typically fan out to 6+ tasks incl. report_gen).
    """
    tasks = plan.tasks or []
    if len(tasks) == 0 or len(tasks) > 3:
        return False
    for t in tasks:
        ttype = getattr(t, "type", None) or (t.get("type") if isinstance(t, dict) else None)
        if ttype == "report_gen":
            return False
    return True


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
