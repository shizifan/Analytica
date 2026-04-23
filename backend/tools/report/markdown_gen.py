"""Markdown Report Generation Skill — Deterministic generation fallback.

Generates a Markdown report from collected content.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.tools.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.tools.registry import register_skill
from backend.tools.report._content_collector import (
    collect_and_associate,
    NarrativeItem, StatsTableItem, GrowthItem,
    ChartDataItem, DataFrameItem, SummaryTextItem,
    ReportContent,
)
from backend.tools.report._kpi_extractor import extract_kpis_llm

logger = logging.getLogger("analytica.tools.report_markdown")

MD_TEMPLATE = """# {title}

**作者**: {author} | **日期**: {date}

---

{content}

---

*本报告由 Analytica 自动生成*
"""


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
    lines = ["| 指标 | " + " | ".join(metrics) + " |",
             "|------|" + "|".join("---" for _ in metrics) + "|"]

    for col, vals in summary_stats.items():
        if not isinstance(vals, dict):
            continue
        cells = " | ".join(_fmt(vals.get(m)) for m in metrics)
        lines.append(f"| **{col}** | {cells} |")

    return "\n".join(lines)


def _render_growth_kpi(growth_rates: dict[str, dict[str, float | None]]) -> str:
    lines = []
    for col, rates in growth_rates.items():
        if not isinstance(rates, dict):
            continue
        parts = []
        yoy = rates.get("yoy")
        if yoy is not None:
            arrow = "↑" if yoy >= 0 else "↓"
            parts.append(f"同比: {arrow}{abs(yoy)*100:.1f}%")
        mom = rates.get("mom")
        if mom is not None:
            arrow = "↑" if mom >= 0 else "↓"
            parts.append(f"环比: {arrow}{abs(mom)*100:.1f}%")
        if parts:
            lines.append(f"- **{col}**: {", ".join(parts)}")
    return "\n".join(lines) if lines else ""


def _render_dataframe(df: Any) -> str:
    if df.empty:
        return "*（无数据）*"

    display = df.head(20)
    header = "| " + " | ".join(str(c) for c in display.columns) + " |"
    separator = "|" + "|".join("---" for _ in display.columns) + "|"
    rows = []
    for _, row in display.iterrows():
        cells = " | ".join(_fmt(v) for v in row)
        rows.append(f"| {cells} |")

    extra = f"\n*（仅展示前 20 行，共 {len(df)} 行）*" if len(df) > 20 else ""
    return "\n".join([header, separator] + rows) + extra


def _render_kpi_md(kpis: list) -> str:
    if not kpis:
        return ""
    lines = ["## 核心指标\n"]
    for k in kpis:
        trend = {"positive": "↑", "negative": "↓"}.get(k.trend or "", "")
        sub = f" （{k.sub}）" if k.sub else ""
        lines.append(f"- **{k.label}**：{trend}{k.value}{sub}")
    return "\n".join(lines) + "\n"


def _build_markdown_deterministic(report: ReportContent) -> str:
    content_parts: list[str] = []

    if report.kpi_cards:
        content_parts.append(_render_kpi_md(report.kpi_cards))

    for i, section in enumerate(report.sections, 1):
        content_parts.append(f"\n## {i}. {section.name}\n")

        for item in section.items:
            if isinstance(item, NarrativeItem):
                content_parts.append(f"\n{item.text}\n")
            elif isinstance(item, StatsTableItem):
                md = _render_stats_table(item.summary_stats)
                if md:
                    content_parts.append(f"\n### 统计数据概览\n\n{md}\n")
            elif isinstance(item, GrowthItem):
                md = _render_growth_kpi(item.growth_rates)
                if md:
                    content_parts.append(f"\n### 增长率指标\n\n{md}\n")
            elif isinstance(item, ChartDataItem):
                chart_title = item.option.get("title", {}).get("text", "图表")
                content_parts.append(f"\n### {chart_title}\n\n*（图表数据，可视化时需配合 ECharts 等工具渲染）*\n")
            elif isinstance(item, DataFrameItem):
                md = _render_dataframe(item.df)
                if md:
                    content_parts.append(f"\n### 数据明细\n\n{md}\n")

    content_parts.append("\n---\n\n## 总结与建议\n")
    if report.summary_items:
        for si in report.summary_items:
            content_parts.append(f"\n- {si.text}\n")
    else:
        content_parts.append("\n- 以上分析基于数据，仅供参考。\n")

    return "\n".join(content_parts)


@register_skill("skill_report_markdown", SkillCategory.REPORT, "Markdown 报告生成（.md 文件）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="Markdown 文件路径")
class MarkdownReportSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        try:
            intent = inp.params.get("intent", "")
            task_id = inp.params.get("__task_id__", "")

            report = collect_and_associate(
                inp.params, context,
                task_order=inp.params.get("_task_order"),
            )
            report.kpi_cards = await extract_kpis_llm(
                intent, context, span_emit=inp.span_emit, task_id=task_id,
            )

            # Build markdown content
            content = _build_markdown_deterministic(report)

            # Assemble final markdown
            md = MD_TEMPLATE.format(
                title=report.title,
                author=report.author,
                date=report.date,
                content=content,
            )

            return SkillOutput(
                skill_id=self.skill_id,
                status="success",
                output_type="file",
                data=md,
                metadata={
                    "format": "markdown",
                    "title": report.title,
                    "char_count": len(md),
                    "line_count": len(md.splitlines()),
                    "mode": "deterministic",
                },
            )

        except Exception as e:
            logger.exception("Markdown generation failed: %s", e)
            return self._fail(str(e))
