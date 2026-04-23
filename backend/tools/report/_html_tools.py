"""HTML tool factory — wraps HTML render functions as LangChain tools.

Usage inside ``HtmlReportSkill.execute()``::

    parts: list[str] = []
    chart_counter = [0]
    tools = make_html_tools(parts, chart_counter, content)
    success = await run_report_agent(llm, tools, HTML_SYSTEM_PROMPT, msg)
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from backend.tools._i18n import metric_label
from backend.tools.report._agent_loop import FINALIZE_SENTINEL
from backend.tools.report._content_collector import (
    ChartDataItem,
    DataFrameItem,
    GrowthItem,
    NarrativeItem,
    ReportContent,
    StatsTableItem,
)

# ---------------------------------------------------------------------------
# Inline render helpers (extracted from html_gen.py)
# ---------------------------------------------------------------------------

def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) >= 1 else f"{v:.4f}"
    return str(v)


def _render_stats_table(summary_stats: dict[str, Any]) -> str:
    first_val = next(iter(summary_stats.values()), None)
    if isinstance(first_val, dict) and not any(k in first_val for k in ("mean", "median", "std", "min", "max")):
        flat: dict[str, dict] = {}
        for gk, cols in summary_stats.items():
            if isinstance(cols, dict):
                for cn, metrics in cols.items():
                    flat[f"{gk}/{cn}"] = metrics if isinstance(metrics, dict) else {}
        summary_stats = flat if flat else summary_stats

    metrics = ["mean", "median", "std", "min", "max"]
    rows = []
    for col, vals in summary_stats.items():
        if not isinstance(vals, dict):
            continue
        cells = "".join(f"<td>{_fmt(vals.get(m))}</td>" for m in metrics)
        rows.append(f"<tr><td><b>{col}</b></td>{cells}</tr>")
    if not rows:
        return ""
    header = "<tr>" + "".join(f"<th>{h}</th>" for h in ["指标"] + [metric_label(m) for m in metrics]) + "</tr>"
    return f'<table class="stats">{header}{"".join(rows)}</table>'


def _render_growth_kpi(growth_rates: dict[str, dict[str, float | None]]) -> str:
    cards = []
    for col, rates in growth_rates.items():
        if not isinstance(rates, dict):
            continue
        parts = []
        yoy = rates.get("yoy")
        if yoy is not None:
            cls = "positive" if yoy >= 0 else "negative"
            arrow = "\u2191" if yoy >= 0 else "\u2193"
            parts.append(f'<div class="value {cls}">{arrow}{abs(yoy)*100:.1f}%</div><div class="sub">同比</div>')
        mom = rates.get("mom")
        if mom is not None:
            cls = "positive" if mom >= 0 else "negative"
            arrow = "\u2191" if mom >= 0 else "\u2193"
            parts.append(f'<div class="value {cls}">{arrow}{abs(mom)*100:.1f}%</div><div class="sub">环比</div>')
        if parts:
            cards.append(f'<div class="kpi-card"><div class="label">{col}</div>{"".join(parts)}</div>')
    return f'<div class="kpi-row">{"".join(cards)}</div>' if cards else ""


def _render_dataframe(df: Any) -> str:
    display = df.head(20)
    header = "<tr>" + "".join(f"<th>{c}</th>" for c in display.columns) + "</tr>"
    rows = []
    for _, row in display.iterrows():
        cells = "".join(f"<td>{_fmt(v)}</td>" for v in row)
        rows.append(f"<tr>{cells}</tr>")
    extra = f"<p><i>（仅展示前 20 行，共 {len(df)} 行）</i></p>" if len(df) > 20 else ""
    return f'<table class="stats">{header}{"".join(rows)}</table>{extra}'


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

HTML_SYSTEM_PROMPT = """\
你是一位专业的 HTML 报告排版师。你的任务是使用提供的工具将分析内容组合成一份结构完整的单页 HTML 报告。

## 排版规范
1. 如果存在 KPI 指标（用户消息中会标注 "KPI 卡片: N 张"），先调用 add_kpi_cards_html
2. 按章节顺序处理每个 Section：先打开章节（add_section_open），添加内容，再关闭章节（add_section_close）
3. 章节内建议的内容顺序：叙述文本 → 增长率 → 统计表格 → 图表 → 数据明细表
4. 最后添加总结（add_summary_html）
5. 完成后必须调用 finalize_html

## 重要规则
- 通过 section_index 和 item_index 引用内容，对应用户消息中的 Section 编号和 [] 编号
- 章节名通常已带中文数字前缀（"一、经营摘要"），调用 add_section_open 只传 title 即可，不要再加 "1." 这类编号
- 不要跳过有内容的章节
- 不要自行编造数据
- 空章节可以跳过
- 每个 section_open 必须有对应的 section_close
"""


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def make_html_tools(
    parts: list[str],
    chart_counter: list[int],
    content: ReportContent,
) -> list:
    """Return LangChain tools that append HTML fragments to *parts* via closure."""

    def _lookup(section_index: int, item_index: int, expected_type: type) -> Any:
        if section_index < 0 or section_index >= len(content.sections):
            raise IndexError(f"section_index={section_index} 越界 (0-{len(content.sections)-1})")
        sec = content.sections[section_index]
        if item_index < 0 or item_index >= len(sec.items):
            raise IndexError(f"item_index={item_index} 越界，Section '{sec.name}' 共 {len(sec.items)} 项")
        item = sec.items[item_index]
        if not isinstance(item, expected_type):
            raise TypeError(
                f"Section[{section_index}][{item_index}] 是 {type(item).__name__}，"
                f"期望 {expected_type.__name__}"
            )
        return item

    # ── Tools ──────────────────────────────────────────────────────

    @tool
    def add_section_open(title: str, number: int | None = None) -> str:
        """打开一个 HTML 章节 div，包含章节标题。

        ``number`` 参数保留向后兼容（旧代理会传），但渲染时忽略——模板的章节名
        已自带 "一、" / "二、" 等中文编号前缀，再叠加阿拉伯数字会出现双重编号。
        """
        _ = number  # intentionally unused (batch 4: no auto-numbering)
        parts.append(f'<div class="section"><h2>{title}</h2>')
        return f"✓ 章节已打开：{title}"

    @tool
    def add_kpi_cards_html() -> str:
        """在报告顶部（第一个 section 之前）添加业务 KPI 卡片行。

        使用内置的 ReportContent.kpi_cards 数据，无需参数。
        """
        from backend.tools.report.html_gen import _render_kpi_cards
        html = _render_kpi_cards(content.kpi_cards)
        if html:
            parts.append(f'<div class="section">{html}</div>')
            return f"✓ KPI 卡片已添加（{len(content.kpi_cards)} 张）"
        return "（无 KPI 可渲染，跳过）"

    @tool
    def add_section_close() -> str:
        """关闭当前章节 div。"""
        parts.append("</div>")
        return "✓ 章节已关闭"

    @tool
    def add_narrative_html(section_index: int, item_index: int) -> str:
        """添加叙述分析文本段落。"""
        item = _lookup(section_index, item_index, NarrativeItem)
        parts.append(f'<div class="narrative">{item.text}</div>')
        return f"✓ 叙述文本已添加（{len(item.text)} 字符）"

    @tool
    def add_stats_table_html(section_index: int, item_index: int) -> str:
        """添加统计数据汇总表格。"""
        item = _lookup(section_index, item_index, StatsTableItem)
        html = _render_stats_table(item.summary_stats)
        if html:
            parts.append(f"<h3>统计数据概览</h3>{html}")
        return f"✓ 统计表格已添加（{len(item.summary_stats)} 列）"

    @tool
    def add_growth_kpi_html(section_index: int, item_index: int) -> str:
        """添加增长率 KPI 卡片。"""
        item = _lookup(section_index, item_index, GrowthItem)
        html = _render_growth_kpi(item.growth_rates)
        if html:
            parts.append(f"<h3>增长率指标</h3>{html}")
        return f"✓ KPI 卡片已添加（{len(item.growth_rates)} 项）"

    @tool
    def add_chart_html(section_index: int, item_index: int) -> str:
        """添加 ECharts 交互式图表。"""
        item = _lookup(section_index, item_index, ChartDataItem)
        chart_id = f"chart_{chart_counter[0]}"
        chart_counter[0] += 1
        chart_json = json.dumps(item.option, ensure_ascii=False)
        parts.append(
            f'<div id="{chart_id}" class="chart-container"></div>'
            f'<script>echarts.init(document.getElementById("{chart_id}")).setOption({chart_json});</script>'
        )
        return f"✓ 图表已添加：{item.title or chart_id}"

    @tool
    def add_dataframe_html(section_index: int, item_index: int) -> str:
        """添加数据明细表格（DataFrame）。"""
        item = _lookup(section_index, item_index, DataFrameItem)
        html = _render_dataframe(item.df)
        if html:
            parts.append(f"<h3>数据明细</h3>{html}")
        return f"✓ 数据明细表已添加（{item.df.shape[0]} 行 × {item.df.shape[1]} 列）"

    @tool
    def add_summary_html() -> str:
        """添加报告末尾的总结与建议。"""
        parts.append('<div class="summary"><h2>总结与建议</h2>')
        if content.summary_items:
            for si in content.summary_items:
                parts.append(f"<p>{si.text}</p>")
        else:
            parts.append("<p>以上分析基于数据，仅供参考。</p>")
        parts.append("</div>")
        return f"✓ 总结章节已添加（{len(content.summary_items)} 条摘要）"

    @tool
    def finalize_html() -> str:
        """完成 HTML 报告编排，结束工具调用。必须在所有内容添加完毕后调用。"""
        return FINALIZE_SENTINEL

    return [
        add_section_open,
        add_section_close,
        add_kpi_cards_html,
        add_narrative_html,
        add_stats_table_html,
        add_growth_kpi_html,
        add_chart_html,
        add_dataframe_html,
        add_summary_html,
        finalize_html,
    ]
