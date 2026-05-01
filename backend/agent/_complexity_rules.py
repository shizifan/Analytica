"""Complexity boundary rules — single source of truth.

Defines tool allow/forbid lists, slot relevance, and task count hints for the
three complexity levels (simple_table / chart_text / full_report). Imported by
schemas, planning, perception, and validation so there is exactly one place to
update when boundaries change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ComplexityLevel = Literal["simple_table", "chart_text", "full_report"]


# ── Validation constants (cross-cutting, not tied to ComplexityRule) ──────

# Data-source tools: every complexity level needs ≥ 1 (api_fetch OR file_parse).
DATA_SOURCE_TOOLS: frozenset[str] = frozenset({
    "tool_api_fetch",
    "tool_file_parse",  # file upload – reserved, not yet supported
})

# Report-file tools: only full_report requires ≥ 1; simple_table / chart_text
# forbid all of them.
REPORT_FILE_TOOLS: frozenset[str] = frozenset({
    "tool_report_html",
    "tool_report_docx",
    "tool_report_pptx",
    "tool_report_markdown",
})

# Chart tools: soft recommendation.  full_report logs a warning when none are
# present; other levels use them optionally.
CHART_TOOLS: frozenset[str] = frozenset({
    "tool_chart_bar",
    "tool_chart_line",
    "tool_chart_waterfall",
    "tool_dashboard",
})


@dataclass(frozen=True)
class ComplexityRule:
    """Unified definition for one complexity level.

    schemas / planning / perception / validation all derive from this table
    so there is no second source of truth to drift out of sync.
    """

    name: ComplexityLevel
    description: str

    # Explicitly forbidden tool_ids (blacklist, does NOT depend on category).
    forbidden_tools: frozenset[str]

    # Slots that are relevant at this complexity level.
    # Used by perception (CONDITION_RULES) and schemas (condition derivation).
    relevant_slots: frozenset[str]

    # Task-count hints for planning prompts (advisory, not enforced).
    task_count_hint_min: int
    task_count_hint_typical: int
    task_count_hint_max_soft: int


# ── Three-level rule table ─────────────────────────────────────────────────

COMPLEXITY_RULES: dict[str, ComplexityRule] = {
    "simple_table": ComplexityRule(
        name="simple_table",
        description="表格类查询，可选切换图表视图",
        forbidden_tools=frozenset({
            # Analysis tools – all forbidden
            "tool_desc_analysis",
            "tool_attribution",
            "tool_prediction",
            "tool_anomaly",
            "tool_summary_gen",
            # Report-file tools – all forbidden (single source: REPORT_FILE_TOOLS)
            *REPORT_FILE_TOOLS,
            # Allowed: tool_api_fetch / tool_file_parse / tool_chart_* / tool_web_search
        }),
        relevant_slots=frozenset({
            "analysis_subject", "time_range", "domain",
            "region", "comparison_type",
            "data_granularity", "time_granularity",
        }),
        task_count_hint_min=1,
        task_count_hint_typical=1,
        task_count_hint_max_soft=2,
    ),
    "chart_text": ComplexityRule(
        name="chart_text",
        description="图文分析，含归因/预测/总结，不出报告文件",
        forbidden_tools=frozenset({
            *REPORT_FILE_TOOLS,
            # Key: tool_summary_gen is ALLOWED (chart_text needs it for summaries)
            # Key: tool_attribution / tool_prediction / tool_anomaly / tool_desc_analysis are ALLOWED
            # Allowed: tool_api_fetch / tool_file_parse / tool_chart_* / tool_web_search
        }),
        relevant_slots=frozenset({
            "analysis_subject", "time_range", "domain",
            "region", "comparison_type",
            "data_granularity", "time_granularity",
            "attribution_needed", "predictive_needed",
        }),
        task_count_hint_min=1,
        task_count_hint_typical=4,
        task_count_hint_max_soft=8,
    ),
    "full_report": ComplexityRule(
        name="full_report",
        description="图文分析 + 可下载文档",
        forbidden_tools=frozenset(),  # nothing forbidden
        relevant_slots=frozenset({
            "analysis_subject", "time_range", "domain",
            "region", "comparison_type",
            "data_granularity", "time_granularity",
            "attribution_needed", "predictive_needed",
            "output_format",
        }),
        task_count_hint_min=3,
        task_count_hint_typical=8,
        task_count_hint_max_soft=20,
    ),
}


# ── Derived helpers ─────────────────────────────────────────────────────────

def get_rule(complexity: str) -> ComplexityRule:
    """Return rule for *complexity*; unknown values degrade to simple_table."""
    return COMPLEXITY_RULES.get(complexity, COMPLEXITY_RULES["simple_table"])


def is_tool_allowed(complexity: str, tool_id: str) -> bool:
    """Check whether *tool_id* is allowed at the given complexity.

    Only checks the *forbidden_tools* blacklist.  Cross-plan-level checks
    (≥1 data source, ≥1 report file for full_report) are handled by the
    validation layer, not by this single-tool helper.
    """
    return tool_id not in get_rule(complexity).forbidden_tools


def get_relevant_slots(complexity: str) -> frozenset[str]:
    """Return the set of fillable slots relevant at this complexity."""
    return get_rule(complexity).relevant_slots


def get_task_count_hint(complexity: str) -> tuple[int, int, int]:
    """Return (min, typical, max_soft) for planning prompt hints."""
    rule = get_rule(complexity)
    return (rule.task_count_hint_min, rule.task_count_hint_typical, rule.task_count_hint_max_soft)
