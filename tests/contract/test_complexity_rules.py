"""Contract tests for _complexity_rules – the single source of truth.

Validates that the forbidden/allowed tables, slot relevance, and task-count
hints are internally consistent and match the spec.
"""

from __future__ import annotations

import pytest

from backend.agent._complexity_rules import (
    CHART_TOOLS,
    COMPLEXITY_RULES,
    DATA_SOURCE_TOOLS,
    REPORT_FILE_TOOLS,
    get_relevant_slots,
    get_rule,
    get_task_count_hint,
    is_tool_allowed,
)

pytestmark = pytest.mark.contract


class TestRuleStructure:
    def test_three_levels_present(self):
        assert set(COMPLEXITY_RULES.keys()) == {"simple_table", "chart_text", "full_report"}

    def test_data_source_constants(self):
        assert "tool_api_fetch" in DATA_SOURCE_TOOLS
        assert "tool_file_parse" in DATA_SOURCE_TOOLS
        assert "tool_report_html" in REPORT_FILE_TOOLS
        assert "tool_report_markdown" in REPORT_FILE_TOOLS

    def test_data_source_disjoint_from_report(self):
        assert DATA_SOURCE_TOOLS & REPORT_FILE_TOOLS == frozenset()

    def test_chart_tools_membership(self):
        for tool in ("tool_chart_bar", "tool_chart_line",
                     "tool_chart_waterfall", "tool_dashboard"):
            assert tool in CHART_TOOLS

    def test_chart_tools_disjoint_from_others(self):
        """CHART_TOOLS must not overlap DATA_SOURCE_TOOLS or REPORT_FILE_TOOLS."""
        assert CHART_TOOLS & DATA_SOURCE_TOOLS == frozenset()
        assert CHART_TOOLS & REPORT_FILE_TOOLS == frozenset()


class TestSimpleTableForbidden:
    def test_forbids_all_analysis(self):
        rule = COMPLEXITY_RULES["simple_table"]
        for tool in ("tool_desc_analysis", "tool_attribution",
                     "tool_prediction", "tool_anomaly", "tool_summary_gen"):
            assert tool in rule.forbidden_tools

    def test_forbids_all_report_files(self):
        rule = COMPLEXITY_RULES["simple_table"]
        assert REPORT_FILE_TOOLS <= rule.forbidden_tools

    def test_allows_charts(self):
        assert is_tool_allowed("simple_table", "tool_chart_bar")
        assert is_tool_allowed("simple_table", "tool_chart_line")

    def test_allows_web_search(self):
        assert is_tool_allowed("simple_table", "tool_web_search")

    def test_allows_data_sources(self):
        assert is_tool_allowed("simple_table", "tool_api_fetch")
        assert is_tool_allowed("simple_table", "tool_file_parse")


class TestChartTextForbidden:
    def test_forbids_only_report_files(self):
        rule = COMPLEXITY_RULES["chart_text"]
        assert rule.forbidden_tools == REPORT_FILE_TOOLS

    def test_allows_summary_gen(self):
        assert is_tool_allowed("chart_text", "tool_summary_gen")

    def test_allows_attribution(self):
        assert is_tool_allowed("chart_text", "tool_attribution")

    def test_allows_prediction(self):
        assert is_tool_allowed("chart_text", "tool_prediction")

    def test_allows_anomaly(self):
        assert is_tool_allowed("chart_text", "tool_anomaly")

    def test_allows_charts_and_search(self):
        assert is_tool_allowed("chart_text", "tool_chart_bar")
        assert is_tool_allowed("chart_text", "tool_web_search")

    def test_forbids_report_files(self):
        for tool in REPORT_FILE_TOOLS:
            assert not is_tool_allowed("chart_text", tool)


class TestFullReportForbidden:
    def test_forbids_nothing(self):
        rule = COMPLEXITY_RULES["full_report"]
        assert rule.forbidden_tools == frozenset()

    def test_allows_everything(self):
        for tool in ("tool_api_fetch", "tool_file_parse",
                     "tool_chart_bar", "tool_desc_analysis",
                     "tool_attribution", "tool_prediction", "tool_anomaly",
                     "tool_summary_gen", "tool_web_search",
                     "tool_report_html", "tool_report_docx",
                     "tool_report_pptx", "tool_report_markdown"):
            assert is_tool_allowed("full_report", tool), f"{tool} 应允许"


class TestSlotRelevance:
    def test_simple_table_no_attribution_or_prediction(self):
        slots = get_relevant_slots("simple_table")
        assert "attribution_needed" not in slots
        assert "predictive_needed" not in slots

    def test_chart_text_includes_attribution_and_prediction(self):
        slots = get_relevant_slots("chart_text")
        assert "attribution_needed" in slots
        assert "predictive_needed" in slots
        assert "output_format" not in slots

    def test_full_report_includes_output_format(self):
        slots = get_relevant_slots("full_report")
        assert "output_format" in slots
        assert "attribution_needed" in slots
        assert "predictive_needed" in slots

    def test_time_and_data_granularity_in_all_three(self):
        for complexity in ("simple_table", "chart_text", "full_report"):
            slots = get_relevant_slots(complexity)
            assert "time_granularity" in slots, f"{complexity} 缺 time_granularity"
            assert "data_granularity" in slots, f"{complexity} 缺 data_granularity"


class TestTaskCountHint:
    def test_hint_ordered(self):
        """min ≤ typical ≤ max_soft"""
        for complexity in ("simple_table", "chart_text", "full_report"):
            min_n, typical, max_soft = get_task_count_hint(complexity)
            assert min_n <= typical <= max_soft

    def test_simple_table_hint_smaller_than_chart_text(self):
        s_max = get_task_count_hint("simple_table")[2]
        c_max = get_task_count_hint("chart_text")[2]
        assert s_max < c_max


class TestUnknownComplexity:
    def test_falls_back_to_simple_table(self):
        rule = get_rule("nonexistent")
        assert rule.name == "simple_table"
        assert is_tool_allowed("nonexistent", "tool_attribution") is False
        assert is_tool_allowed("nonexistent", "tool_api_fetch") is True
