"""HTML BlockRenderer — 辽港数据期刊 PR-2 全量重写。

应用辽港集团 VI 标准色 (PANTONE 293 C + 872 U) 和编辑型
数据期刊布局。统一设计 Token 通过 CSS 变量管理，图表使用
ECharts + "liangang-journal" 注册主题。
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from backend.tools._field_labels import col_label, metric_label
from backend.tools.report._block_renderer import BlockRendererBase
from backend.tools.report._echarts_theme import liangang_journal_echarts_theme_js
from backend.tools.report._outline import (
    Asset,
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GrowthIndicatorsBlock,
    KpiRowBlock,
    KpiStripBlock,
    KpiStripItem,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    StatsAsset,
    TableAsset,
    TableBlock,
)
from backend.tools.report._typography import cn_latin_spacing

# ---------------------------------------------------------------------------
# HTML Template — 辽港数据期刊视觉系统
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
{echarts_theme}
<style>
:root {{
  --paper: #FBF6EE;
  --paper-2: #F4ECDF;
  --ink-1: #1F1A12;
  --ink-2: #5E5648;
  --ink-3: #9A8E78;
  --rule: rgba(31,26,18,0.20);
  --rule-strong: #004889;
  --primary: #004889;
  --primary-70: #336EA4;
  --primary-50: #80A4C2;
  --accent: #AC916B;
  --accent-60: #CFAB79;
  --accent-dark: #8B4A2B;
  --alert: #A8341E;
  --font-display: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun", serif;
  --font-body: var(--font-display);
  --font-ui: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", "IBM Plex Mono", "Consolas", "Menlo", monospace;
}}

body {{
  background: var(--paper);
  color: var(--ink-1);
  font-family: var(--font-body);
  font-size: 16px; line-height: 1.85;
  font-variant-numeric: tabular-nums lining-nums;
  max-width: 840px; margin: 0 auto;
  padding: 64px 56px 96px;
  hanging-punctuation: allow-end last;
}}

/* ── 标题 ── */
h1 {{
  font-family: var(--font-display); font-weight: 700;
  color: var(--primary); font-size: 42px;
  line-height: 1.2; margin: 0 0 8px;
}}
.meta {{
  font-family: var(--font-ui); font-size: 11px;
  color: var(--ink-3); margin-bottom: 48px;
  letter-spacing: .08em; text-transform: uppercase;
}}
.kicker {{
  font-family: var(--font-ui); font-size: 11px;
  letter-spacing: .12em; text-transform: uppercase;
  color: var(--primary); font-feature-settings: "smcp";
}}

/* ── 章节 ── */
.section {{
  padding-top: 32px; border-top: 1px solid var(--rule-strong);
  margin-top: 32px;
}}
.section:first-of-type {{ border-top: none; }}
h2 {{
  font-family: var(--font-display); font-weight: 700;
  font-size: 28px; color: var(--ink-1);
  margin: 0 0 16px;
}}

/* ── Lede & Narrative ── */
.lede {{
  font-family: var(--font-body); font-style: italic;
  font-size: 18px; color: var(--ink-2);
  margin: 16px 0 24px; line-height: 1.75;
}}
.lede:first-letter {{
  font-size: 4em; line-height: .85; float: left;
  padding: 4px 8px 0 0; color: var(--primary);
}}
.narrative {{
  text-indent: 2em; margin: 14px 0; line-height: 1.85;
}}

/* ── Chart Figure ── */
.chart-fig {{
  margin: 32px 0;
}}
.chart-fig header {{
  border-top: 1px solid var(--rule);
  padding-top: 12px; margin-bottom: 16px;
}}
.fig-title {{
  font-family: var(--font-display); font-size: 16px;
  font-weight: 600; margin: 0 0 4px; color: var(--ink-1);
}}
.fig-sub {{
  font-family: var(--font-ui); font-size: 12px;
  color: var(--ink-2); margin: 0;
}}
.chart-container {{
  width: 100%; height: 360px;
}}
.fig-note {{
  font-family: var(--font-ui); font-style: italic;
  font-size: 11px; color: var(--ink-3);
  border-top: 1px solid var(--rule);
  padding-top: 8px; margin-top: 12px;
}}

/* ── KPI Strip ── */
.kpi-strip {{
  display: grid; grid-template-columns: repeat(4, 1fr);
  border-top: 1px solid var(--primary);
  border-bottom: 1px solid var(--primary);
  margin: 24px 0;
}}
.kpi-cell {{
  padding: 16px 20px; border-right: 1px solid var(--rule);
}}
.kpi-cell:last-child {{ border-right: 0; }}
.kpi-cell .label {{
  font-family: var(--font-ui); font-size: 11px;
  letter-spacing: .08em; text-transform: uppercase;
  color: var(--ink-3);
}}
.kpi-cell .value {{
  font-family: var(--font-mono); font-size: 36px;
  font-weight: 500; color: var(--primary);
  letter-spacing: -0.02em; line-height: 1; margin-top: 4px;
}}
.kpi-cell .value.loss {{ color: var(--accent-dark); }}
.kpi-cell .sub {{
  font-family: var(--font-ui); font-size: 11px;
  color: var(--ink-3); margin-top: 2px;
}}

/* ── Agate Table ── */
table.agate {{
  width: 100%; border-collapse: collapse;
  font-size: 13px; font-family: var(--font-mono);
  margin: 16px 0;
}}
table.agate thead th {{
  font-family: var(--font-ui); font-size: 11px;
  font-weight: 500; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-3);
  padding: 10px 12px; border-top: 1px solid var(--ink-1);
  border-bottom: 1px solid var(--rule); text-align: left;
}}
table.agate tbody td {{
  font-family: var(--font-mono); font-size: 13px;
  padding: 8px 12px;
}}
table.agate tbody td.cat {{
  font-family: var(--font-body);
}}
table.agate td.num {{
  text-align: right; font-variant-numeric: tabular-nums;
}}
table.agate tbody tr:last-child td {{
  border-bottom: 1px solid var(--ink-1);
}}

/* ── Collapsed data ── */
details.full-data {{
  margin: 12px 0;
}}
details.full-data > summary {{
  font-family: var(--font-ui); font-style: italic;
  font-size: 13px; color: var(--ink-2); cursor: pointer;
}}

/* ── Pull-quote & Callout ── */
blockquote.pull {{
  border-left: 4px solid var(--accent); margin: 24px 0;
  padding-left: 24px; font-family: var(--font-display);
  font-style: italic; font-size: 22px; line-height: 1.4;
  color: var(--ink-1);
}}
.callout {{
  border-left: 3px solid var(--accent);
  background: rgba(0,0,0,0.02); padding: 12px 16px;
  margin: 16px 0; line-height: 1.7;
}}
.callout.warn {{
  border-left-color: var(--alert);
}}

/* ── Endmark ── */
.endmark {{
  display: inline-block; width: 8px; height: 8px;
  background: var(--accent); margin-left: 6px;
  vertical-align: middle;
}}

/* ── Comparison Grid ── */
.comparison-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px; margin: 24px 0;
}}
.comparison-col {{
  background: var(--paper-2); border-radius: 0;
  overflow: hidden;
}}
.comparison-col .col-title {{
  background: var(--primary); color: var(--paper);
  padding: 10px 16px; font-family: var(--font-display);
  font-size: 14px; font-weight: 600; text-align: center;
}}
.comparison-col ul {{
  padding: 12px 16px 16px 32px; margin: 0;
  line-height: 1.7; font-size: 13px;
}}

/* ── KPI Cards (global) ── */
.kpi-row {{
  display: flex; gap: 16px; margin: 16px 0 32px;
  flex-wrap: wrap;
}}
.kpi-card {{
  flex: 1; min-width: 160px; background: var(--paper-2);
  padding: 16px; text-align: center;
  border-left: 4px solid var(--accent);
}}
.kpi-card .label {{
  font-family: var(--font-ui); font-size: 11px;
  color: var(--ink-3); margin-bottom: 4px;
}}
.kpi-card .value {{
  font-family: var(--font-mono); font-size: 28px;
  font-weight: bold;
}}
.kpi-card .value.positive {{ color: var(--primary); }}
.kpi-card .value.negative {{ color: var(--accent-dark); }}
.kpi-card .sub {{
  font-family: var(--font-ui); font-size: 11px;
  color: var(--ink-3);
}}

/* ── Appendix ── */
.summary {{
  background: var(--primary); color: var(--paper);
  padding: 20px; margin-top: 40px;
}}
.summary h2 {{ color: var(--accent); font-size: 22px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">{author} | {date}</div>
{content}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) >= 1 else f"{v:.4f}"
    return str(v)


def _fmt_kpi_value(value: str, trend: str = "") -> str:
    """Render a KPI strip cell value with optional trend class."""
    trend_cls = ' class="loss"' if trend == "loss" else ""
    return f"<div{trend_cls}>{value}</div>"


def _render_kpi_cards(items) -> str:
    """Render global KPI summary cards (top of document)."""
    if not items:
        return ""
    cards: list[str] = []
    for k in items:
        trend_cls = f" {k.trend}" if hasattr(k, "trend") and k.trend else ""
        sub_html = f'<div class="sub">{k.sub}</div>' if k.sub else ""
        cards.append(
            f'<div class="kpi-card">'
            f'<div class="label">{k.label}</div>'
            f'<div class="value{trend_cls}">{k.value}</div>'
            f"{sub_html}"
            f"</div>"
        )
    return f'<div class="kpi-row">{"".join(cards)}</div>'


def _render_kpi_strip(items: tuple[KpiStripItem, ...]) -> str:
    """Render the 4-cell KPI strip."""
    cells: list[str] = []
    for it in items:
        val_cls = ' class="loss"' if it.trend == "loss" else ""
        sub_html = f'<div class="sub">{it.sub}</div>' if it.sub else ""
        cells.append(
            f'<div class="kpi-cell">'
            f'<div class="label">{it.label}</div>'
            f'<div class="value{val_cls}">{it.value}</div>'
            f"{sub_html}"
            f"</div>"
        )
    return f'<div class="kpi-strip">{"".join(cells)}</div>'


def _render_stats_table(summary_stats: dict[str, Any]) -> str:
    first_val = next(iter(summary_stats.values()), None)
    if isinstance(first_val, dict) and not any(
        k in first_val for k in ("mean", "median", "std", "min", "max")
    ):
        flat: dict[str, dict] = {}
        for gk, cols in summary_stats.items():
            if isinstance(cols, dict):
                for cn, metrics in cols.items():
                    flat[f"{gk}/{cn}"] = metrics if isinstance(metrics, dict) else {}
        summary_stats = flat if flat else summary_stats

    metrics = ["mean", "median", "std", "min", "max"]
    rows: list[str] = []
    for col, vals in summary_stats.items():
        if not isinstance(vals, dict):
            continue
        cells = "".join(f'<td class="num">{_fmt(vals.get(m))}</td>' for m in metrics)
        rows.append(f"<tr><td>{col}</td>{cells}</tr>")
    if not rows:
        return ""
    header = (
        "<tr>"
        + "".join(f"<th>{h}</th>" for h in ["指标"] + [metric_label(m) for m in metrics])
        + "</tr>"
    )
    return f'<table class="agate">{header}{"".join(rows)}</table>'


def _render_growth_cards(growth_rates: dict[str, dict[str, float | None]]) -> str:
    cards: list[str] = []
    for col, rates in growth_rates.items():
        if not isinstance(rates, dict):
            continue
        parts: list[str] = []
        yoy = rates.get("yoy")
        if yoy is not None:
            cls = "positive" if yoy >= 0 else "negative"
            arrow = "↑" if yoy >= 0 else "↓"
            parts.append(
                f'<div class="value {cls}">{arrow}{abs(yoy)*100:.1f}%</div>'
                f'<div class="sub">同比</div>'
            )
        mom = rates.get("mom")
        if mom is not None:
            cls = "positive" if mom >= 0 else "negative"
            arrow = "↑" if mom >= 0 else "↓"
            parts.append(
                f'<div class="value {cls}">{arrow}{abs(mom)*100:.1f}%</div>'
                f'<div class="sub">环比</div>'
            )
        if parts:
            cards.append(
                f'<div class="kpi-card">'
                f'<div class="label">{col_label(col)}</div>'
                f'{"".join(parts)}'
                f'</div>'
            )
    return f'<div class="kpi-row">{"".join(cards)}</div>' if cards else ""


# HTML 报告中表格的最大显示行数。**不是** silent fallback —
# 完整 DataFrame 仍存放在 ToolOutput.data 里，下游 PPTX/DOCX 渲染走
# 各自的 max_rows 参数；本常量只控制 HTML 报告 UI 上的可读性截断
# （超过 ~20 行的表格在浏览器里几乎没法读）。V6 §12 #11 审计时会
# grep 到这一行，命名常量 + 这条注释让结论"显示层截断、合规"
# 立刻可见。
_HTML_TABLE_MAX_DISPLAY_ROWS = 20


def _render_dataframe(
    df: pd.DataFrame,
    *,
    highlight_rules: list | None = None,
    theme=None,
) -> str:
    if df is None or df.empty:
        return ""
    display = df.head(_HTML_TABLE_MAX_DISPLAY_ROWS)

    headers_list = [str(c) for c in display.columns]
    n_rows = len(display)
    cell_colors: dict[tuple[int, int], tuple[int, int, int]] = {}
    if highlight_rules and theme is not None:
        from backend.tools.report._table_highlight import resolve_cell_highlights
        cell_colors = resolve_cell_highlights(headers_list, n_rows, highlight_rules, theme)

    # Detect numeric columns
    num_cols = set()
    for ci, col in enumerate(display.columns):
        if pd.api.types.is_numeric_dtype(display[col]):
            num_cols.add(ci)

    header = "<tr>" + "".join(f"<th>{c}</th>" for c in headers_list) + "</tr>"
    rows: list[str] = []
    for ri, (_, row) in enumerate(display.iterrows()):
        cell_chunks: list[str] = []
        for ci, v in enumerate(row):
            highlight = cell_colors.get((ri, ci))
            cls = ' class="num"' if ci in num_cols else ""
            if highlight is not None:
                lum = 0.299 * highlight[0] + 0.587 * highlight[1] + 0.114 * highlight[2]
                fg = "#FFFFFF" if lum < 140 else "#1E293B"
                bg = f"rgb({highlight[0]},{highlight[1]},{highlight[2]})"
                cell_chunks.append(
                    f'<td style="background:{bg};color:{fg};font-weight:bold;">'
                    f'{_fmt(v)}</td>'
                )
            else:
                cell_chunks.append(f"<td{cls}>{_fmt(v)}</td>")
        rows.append(f"<tr>{''.join(cell_chunks)}</tr>")
    extra = (
        f"<p><i>（仅展示前 20 行，共 {len(df)} 行）</i></p>"
        if len(df) > 20 else ""
    )
    return f'<table class="agate">{header}{"".join(rows)}</table>{extra}'


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class HtmlBlockRenderer(BlockRendererBase):
    _step_label = "Step 6"

    FOLD_ROW_THRESHOLD = 6

    def __init__(self, theme=None) -> None:  # noqa: ANN001
        super().__init__(theme=theme)
        self._parts: list[str] = []
        self._title: str = ""
        self._author: str = ""
        self._date: str = ""
        self._chart_idx: int = 0
        self._is_appendix: bool = False
        self._appendix_emit_count: int = 0
        self._pending_section_close: bool = False

    @property
    def chart_count(self) -> int:
        return self._chart_idx

    # ---- Lifecycle -----------------------------------------------------

    def begin_document(self, outline: ReportOutline) -> None:
        self._title = outline.metadata.get("title", "")
        self._author = outline.metadata.get("author", "")
        self._date = outline.metadata.get("date", "")
        kpi_html = _render_kpi_cards(outline.kpi_summary)
        if kpi_html:
            self._parts.append(f'<div class="section">{kpi_html}</div>')

    def end_document(self) -> str:
        if self._pending_section_close:
            self._parts.append("</div>")
            self._pending_section_close = False
        content = "\n".join(self._parts)
        # 中英自动加空格
        content = cn_latin_spacing(content)
        return HTML_TEMPLATE.format(
            title=self._title,
            author=self._author,
            date=self._date,
            content=content,
            echarts_theme=liangang_journal_echarts_theme_js(),
        )

    def begin_section(self, section: OutlineSection, index: int) -> None:
        if section.role != "appendix" and self._pending_section_close:
            self._parts.append("</div>")
            self._pending_section_close = False

        if section.role == "appendix":
            self._is_appendix = True
            self._appendix_emit_count = 0
            self._parts.append(f'<div class="summary"><h2>{section.name}</h2>')
        else:
            self._is_appendix = False
            self._parts.append(f'<div class="section"><h2>{section.name}</h2>')

    def end_section(self, section: OutlineSection, index: int) -> None:
        if self._is_appendix:
            if self._appendix_emit_count == 0:
                self._parts.append("<p>以上分析基于数据，仅供参考。</p>")
            self._parts.append("</div>")
            if self._pending_section_close:
                self._parts.append("</div>")
                self._pending_section_close = False
        else:
            self._pending_section_close = True

    # ---- Block emitters ------------------------------------------------

    def emit_kpi_row(self, block: KpiRowBlock) -> None:
        return None

    def emit_kpi_strip(self, block: KpiStripBlock) -> None:
        if block.items:
            self._parts.append(_render_kpi_strip(block.items))

    def emit_paragraph(self, block: ParagraphBlock) -> None:
        if block.style == "callout-warn":
            self._parts.append(f'<div class="callout warn">{block.text}</div>')
            return
        if block.style == "callout-info":
            self._parts.append(f'<div class="callout">{block.text}</div>')
            return
        if block.style == "lead":
            self._parts.append(f'<div class="lede">{block.text}</div>')
            return

        if self._is_appendix:
            self._parts.append(f"<p>{block.text}</p>")
            self._appendix_emit_count += 1
        else:
            self._parts.append(f'<div class="narrative">{block.text}</div>')

    def emit_table(self, block: TableBlock, asset: Asset) -> None:
        if isinstance(asset, StatsAsset):
            html = _render_stats_table(asset.summary_stats)
            if html:
                self._parts.append(html)
        elif isinstance(asset, TableAsset):
            df = (
                pd.DataFrame.from_records(asset.df_records)
                if asset.df_records
                else pd.DataFrame()
            )
            n_rows = len(df)
            html = _render_dataframe(
                df, highlight_rules=block.highlight_rules, theme=self._theme,
            )
            if not html:
                return
            heading = block.caption or "数据明细"
            if n_rows >= self.FOLD_ROW_THRESHOLD:
                self._parts.append(
                    f'<details class="full-data">'
                    f'<summary>展开完整数据 ({n_rows} 行)</summary>'
                    f'{html}'
                    f'</details>'
                )
            else:
                self._parts.append(f"<h3>{heading}</h3>{html}")

    def emit_chart(self, block: ChartBlock, asset: Asset) -> None:
        option = getattr(asset, "option", None)
        if not isinstance(option, dict):
            return
        chart_id = f"chart_{self._chart_idx}"
        self._chart_idx += 1

        enriched = self._enrich_option_for_html(option)
        chart_json = json.dumps(enriched, ensure_ascii=False)

        title = getattr(block, "title", "") or block.caption or ""
        subtitle = getattr(block, "subtitle", "") or ""
        source = getattr(block, "source", "") or ""

        header_html = ""
        if title:
            header_html = f"<header><h3 class=\"fig-title\">{title}</h3>"
            if subtitle:
                header_html += f"<p class=\"fig-sub\">{subtitle}</p>"
            header_html += "</header>"

        footer_html = ""
        if source:
            footer_html = f"<footer><p class=\"fig-note\">{source}</p></footer>"

        self._parts.append(
            f'<figure class="chart-fig">'
            f'{header_html}'
            f'<div id="{chart_id}" class="chart-container" '
            f'data-chart-type="{self._detect_html_chart_type(option)}"></div>'
            f'{footer_html}'
            f'</figure>'
            f'<script>(function(){{var run=function(){{'
            f'var c=echarts.init(document.getElementById("{chart_id}"),'
            f'"liangang-journal");'
            f'c.setOption({chart_json});'
            f'window.addEventListener("resize",function(){{c.resize();}});'
            f'}};if(document.readyState!=="loading")requestAnimationFrame(run);'
            f'else document.addEventListener("DOMContentLoaded",run);}})();</script>'
        )

    @staticmethod
    def _detect_html_chart_type(option: dict) -> str:
        series = option.get("series") or []
        if not series:
            return "unknown"
        types = {(s.get("type") or "").lower() for s in series}
        if {"bar", "line"}.issubset(types):
            return "combo"
        return next(iter(types), "unknown")

    @staticmethod
    def _enrich_option_for_html(option: dict) -> dict:
        import copy

        out = dict(option)
        if "tooltip" not in out:
            out["tooltip"] = {"trigger": "axis"}
        series = out.get("series") or []
        if (
            len(series) == 1
            and isinstance(series[0], dict)
            and (series[0].get("type") or "").lower() == "bar"
            and not series[0].get("label")
        ):
            new_series = copy.deepcopy(series)
            new_series[0]["label"] = {"show": True, "position": "top"}
            y_axis = out.get("yAxis") or {}
            if isinstance(y_axis, list):
                y_axis = y_axis[0] if y_axis else {}
            if isinstance(y_axis, dict) and y_axis.get("type") == "category":
                new_series[0]["label"]["position"] = "right"
            out["series"] = new_series
        return out

    def emit_chart_table_pair(
        self,
        block: ChartTablePairBlock,
        chart_asset: Asset,
        table_asset: Asset,
    ) -> None:
        """纵向布局：图在上 → KPI strip（若有）→ 表格折叠在 details 中。"""
        title = getattr(block, "title", "") or ""
        subtitle = getattr(block, "subtitle", "") or ""
        source = getattr(block, "source", "") or ""

        # Render chart with title/subtitle/source
        synth_chart = ChartBlock(
            block_id=block.block_id,
            asset_id=block.chart_asset_id,
            caption=title,
            title=title,
            subtitle=subtitle,
            source=source,
        )
        self.emit_chart(synth_chart, chart_asset)

        # Render KPI strip if present
        if block.kpi_strip is not None and block.kpi_strip.items:
            self.emit_kpi_strip(block.kpi_strip)

        # Render table (collapsed if not show_full_table)
        if isinstance(table_asset, TableAsset) and table_asset.df_records:
            df = pd.DataFrame.from_records(table_asset.df_records)
            html = _render_dataframe(
                df, highlight_rules=None, theme=self._theme,
            )
            if html:
                n_rows = len(df)
                if block.show_full_table:
                    self._parts.append(html)
                else:
                    self._parts.append(
                        f'<details class="full-data">'
                        f'<summary>展开完整数据 ({n_rows} 行)</summary>'
                        f'{html}'
                        f'</details>'
                    )

    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None:
        if not block.columns:
            return
        cards: list[str] = []
        for col in block.columns:
            items_html = "".join(f"<li>{it}</li>" for it in col.items)
            cards.append(
                f'<div class="comparison-col">'
                f'<div class="col-title">{col.title}</div>'
                f"<ul>{items_html}</ul>"
                f"</div>"
            )
        self._parts.append(
            f'<div class="comparison-grid">{"".join(cards)}</div>'
        )

    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None:
        if block.growth_rates:
            html = _render_growth_cards(block.growth_rates)
            if html:
                self._parts.append(html)

    def emit_section_cover(self, block: SectionCoverBlock) -> None:
        return None
