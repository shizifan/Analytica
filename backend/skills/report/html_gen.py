"""HTML Report Generation Skill — Skill mode (LLM + tools) with deterministic fallback.

Orchestrator: delegates metadata/content extraction to ``_content_collector``,
then either runs an LLM agent loop that composes the HTML using tools,
or falls back to a deterministic builder.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill
from backend.skills.report._content_collector import (
    collect_and_associate,
    NarrativeItem, StatsTableItem, GrowthItem,
    ChartDataItem, DataFrameItem, SummaryTextItem,
    ReportContent,
)
from backend.skills.report import _theme as T
from backend.skills._i18n import metric_label

logger = logging.getLogger("analytica.skills.report_html")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
body {{ font-family: '{font_cn}', sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; color: {text_dark}; }}
h1 {{ color: {primary}; text-align: center; border-bottom: 3px solid {accent}; padding-bottom: 10px; }}
h2 {{ color: {primary}; margin-top: 30px; }}
h3 {{ color: {secondary}; }}
.meta {{ text-align: center; color: #666; margin-bottom: 30px; }}
.section {{ margin-bottom: 40px; }}
.chart-container {{ width: 100%; height: 400px; margin: 20px 0; }}
.narrative {{ line-height: 1.8; text-indent: 2em; }}
.summary {{ background: {primary}; color: white; padding: 20px; border-radius: 8px; margin-top: 40px; }}
.summary h2 {{ color: {accent}; }}
table.stats {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
table.stats th {{ background: {primary}; color: white; padding: 8px 12px; text-align: left; font-size: 13px; }}
table.stats td {{ padding: 8px 12px; border-bottom: 1px solid #e0e0e0; font-size: 13px; font-family: '{font_num}', monospace; }}
table.stats tr:nth-child(even) {{ background: {bg_light}; }}
.kpi-row {{ display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }}
.kpi-card {{ flex: 1; min-width: 180px; background: {bg_light}; border-radius: 8px; padding: 16px; text-align: center; border-left: 4px solid {accent}; }}
.kpi-card .label {{ font-size: 12px; color: {neutral}; margin-bottom: 4px; }}
.kpi-card .value {{ font-size: 28px; font-weight: bold; font-family: '{font_num}', monospace; }}
.kpi-card .value.positive {{ color: {positive}; }}
.kpi-card .value.negative {{ color: {negative}; }}
.kpi-card .sub {{ font-size: 11px; color: {neutral}; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">{author} | {date}</div>
{content}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Inline render helpers (used by both deterministic and tool paths)
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
# Deterministic builder (extracted from the original execute body)
# ---------------------------------------------------------------------------

def _render_kpi_cards(kpis: list) -> str:
    """Render ``ReportContent.kpi_cards`` as a .kpi-row HTML block.

    Empty input → empty string (renderer skips the block entirely instead
    of producing a stray empty card row).
    """
    if not kpis:
        return ""
    cards = []
    for k in kpis:
        trend_cls = f" {k.trend}" if k.trend else ""
        sub_html = f'<div class="sub">{k.sub}</div>' if k.sub else ""
        cards.append(
            f'<div class="kpi-card">'
            f'<div class="label">{k.label}</div>'
            f'<div class="value{trend_cls}">{k.value}</div>'
            f'{sub_html}'
            f'</div>'
        )
    return f'<div class="kpi-row">{"".join(cards)}</div>'


def _build_html_deterministic(report: ReportContent) -> tuple[list[str], int]:
    """Build HTML fragments using hardcoded ordering — the fallback path.

    Returns ``(parts, chart_count)``.
    """
    content_parts: list[str] = []
    chart_idx = 0

    # KPI row rendered once, before section 1 (batch 4)
    kpi_html = _render_kpi_cards(report.kpi_cards)
    if kpi_html:
        content_parts.append(f'<div class="section">{kpi_html}</div>')

    for section in report.sections:
        # Chinese section names already carry numbering prefixes like "一、", so
        # we no longer auto-prepend "1." (pre-batch-4 rendered "1. 一、经营摘要").
        content_parts.append(f'<div class="section"><h2>{section.name}</h2>')

        for item in section.items:
            if isinstance(item, NarrativeItem):
                content_parts.append(f'<div class="narrative">{item.text}</div>')
            elif isinstance(item, StatsTableItem):
                html = _render_stats_table(item.summary_stats)
                if html:
                    content_parts.append(f"<h3>统计数据概览</h3>{html}")
            elif isinstance(item, GrowthItem):
                html = _render_growth_kpi(item.growth_rates)
                if html:
                    content_parts.append(f"<h3>增长率指标</h3>{html}")
            elif isinstance(item, ChartDataItem):
                chart_id = f"chart_{chart_idx}"
                chart_idx += 1
                chart_json = json.dumps(item.option, ensure_ascii=False)
                content_parts.append(
                    f'<div id="{chart_id}" class="chart-container"></div>'
                    f'<script>echarts.init(document.getElementById("{chart_id}")).setOption({chart_json});</script>'
                )
            elif isinstance(item, DataFrameItem):
                html = _render_dataframe(item.df)
                if html:
                    content_parts.append(f"<h3>数据明细</h3>{html}")

        content_parts.append("</div>")

    content_parts.append('<div class="summary"><h2>总结与建议</h2>')
    if report.summary_items:
        for si in report.summary_items:
            content_parts.append(f"<p>{si.text}</p>")
    else:
        content_parts.append("<p>以上分析基于数据，仅供参考。</p>")
    content_parts.append("</div>")

    return content_parts, chart_idx


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------

@register_skill("skill_report_html", SkillCategory.REPORT, "HTML 报告生成（单页 HTML 文件）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="HTML 文件路径")
class HtmlReportSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        try:
            report = collect_and_associate(
                inp.params, context,
                task_order=inp.params.get("_task_order"),
            )

            # ── Try Skill mode (LLM agent loop) ──
            mode = "deterministic_fallback"
            content_parts: list[str] = []
            chart_counter = [0]

            try:
                from backend.config import get_settings

                settings = get_settings()
                if not settings.REPORT_AGENT_ENABLED:
                    raise RuntimeError("agent mode disabled by config")

                from langchain_openai import ChatOpenAI

                from backend.skills.report._agent_loop import run_report_agent, serialize_report_content
                from backend.skills.report._html_tools import HTML_SYSTEM_PROMPT, make_html_tools

                llm = ChatOpenAI(
                    base_url=settings.QWEN_API_BASE,
                    api_key=settings.QWEN_API_KEY,
                    model=settings.QWEN_MODEL,
                    temperature=0.2,
                    request_timeout=90,
                    extra_body={"enable_thinking": False},
                )

                tools = make_html_tools(content_parts, chart_counter, report)
                user_message = serialize_report_content(report)
                success = await run_report_agent(llm, tools, HTML_SYSTEM_PROMPT, user_message)

                if success:
                    mode = "llm_agent"
                else:
                    logger.warning("HTML agent did not finalise; falling back to deterministic")
                    content_parts, chart_count_val = _build_html_deterministic(report)
                    chart_counter[0] = chart_count_val

            except Exception as agent_err:
                logger.warning("HTML agent loop failed (%s); falling back to deterministic", agent_err)
                content_parts, chart_count_val = _build_html_deterministic(report)
                chart_counter[0] = chart_count_val
                mode = "deterministic_fallback_error"

            # ── Assemble final HTML ──
            html = HTML_TEMPLATE.format(
                title=report.title,
                author=report.author,
                date=report.date,
                content="\n".join(content_parts),
                font_cn=T.FONT_CN,
                font_num=T.FONT_NUM,
                primary=T.PRIMARY,
                secondary=T.SECONDARY,
                accent=T.ACCENT,
                positive=T.POSITIVE,
                negative=T.NEGATIVE,
                neutral=T.NEUTRAL,
                bg_light=T.BG_LIGHT,
                text_dark=T.TEXT_DARK,
            )

            return SkillOutput(
                skill_id=self.skill_id,
                status="success",
                output_type="file",
                data=html,
                metadata={
                    "format": "html",
                    "title": report.title,
                    "chart_count": chart_counter[0],
                    "mode": mode,
                },
            )

        except Exception as e:
            logger.exception("HTML generation failed: %s", e)
            return self._fail(str(e))
