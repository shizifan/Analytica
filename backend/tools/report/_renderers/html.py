"""HTML BlockRenderer — Step 6.

Output is byte-for-byte equivalent to the previous
``_build_html_deterministic`` path (guarded by Step 0 baseline).

Note on script handling: ECharts initialiser scripts are emitted inline
right after their target ``<div>`` (matching legacy behaviour) — we do
not split them into a trailing ``<script>`` block, so the renderer only
needs a single ``_parts`` buffer.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from backend.tools._field_labels import metric_label
from backend.tools.report import _theme as T
from backend.tools.report._block_renderer import BlockRendererBase
from backend.tools.report._kpi_extractor import KPIItem
from backend.tools.report._outline import (
    Asset,
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GrowthIndicatorsBlock,
    KpiRowBlock,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    StatsAsset,
    TableAsset,
    TableBlock,
)


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
# Render helpers
# ---------------------------------------------------------------------------

def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) >= 1 else f"{v:.4f}"
    return str(v)


def _render_kpi_cards(kpis: list[KPIItem]) -> str:
    if not kpis:
        return ""
    cards: list[str] = []
    for k in kpis:
        trend_cls = f" {k.trend}" if k.trend else ""
        sub_html = f'<div class="sub">{k.sub}</div>' if k.sub else ""
        cards.append(
            f'<div class="kpi-card">'
            f'<div class="label">{k.label}</div>'
            f'<div class="value{trend_cls}">{k.value}</div>'
            f"{sub_html}"
            f"</div>"
        )
    return f'<div class="kpi-row">{"".join(cards)}</div>'


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
        cells = "".join(f"<td>{_fmt(vals.get(m))}</td>" for m in metrics)
        rows.append(f"<tr><td><b>{col}</b></td>{cells}</tr>")
    if not rows:
        return ""
    header = (
        "<tr>"
        + "".join(f"<th>{h}</th>" for h in ["指标"] + [metric_label(m) for m in metrics])
        + "</tr>"
    )
    return f'<table class="stats">{header}{"".join(rows)}</table>'


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
                f'<div class="label">{col}</div>'
                f'{"".join(parts)}'
                f'</div>'
            )
    return f'<div class="kpi-row">{"".join(cards)}</div>' if cards else ""


def _render_dataframe(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    display = df.head(20)
    header = "<tr>" + "".join(f"<th>{c}</th>" for c in display.columns) + "</tr>"
    rows: list[str] = []
    for _, row in display.iterrows():
        cells = "".join(f"<td>{_fmt(v)}</td>" for v in row)
        rows.append(f"<tr>{cells}</tr>")
    extra = (
        f"<p><i>（仅展示前 20 行，共 {len(df)} 行）</i></p>"
        if len(df) > 20 else ""
    )
    return f'<table class="stats">{header}{"".join(rows)}</table>{extra}'


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class HtmlBlockRenderer(BlockRendererBase):
    _step_label = "Step 6"

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._title: str = ""
        self._author: str = ""
        self._date: str = ""
        self._chart_idx: int = 0
        self._is_appendix: bool = False
        self._appendix_emit_count: int = 0
        # Lazy-close pattern: defer emitting ``</div>`` for a non-appendix
        # section until the next ``begin_section`` arrives. If the next
        # one is an appendix, the close is held until after the appendix
        # closes — replicates legacy output where the summary div ended up
        # nested inside the final section. (See golden HTML L45-L49.)
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
        # If the outline ended with a non-appendix section we still have
        # its close pending — flush before rendering the template.
        if self._pending_section_close:
            self._parts.append("</div>")
            self._pending_section_close = False
        return HTML_TEMPLATE.format(
            title=self._title,
            author=self._author,
            date=self._date,
            content="\n".join(self._parts),
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

    def begin_section(self, section: OutlineSection, index: int) -> None:
        # Flush any held-back close from the previous non-appendix section
        # *only if* this section is also non-appendix. Appendix swallows
        # the previous section's close so the legacy nested layout is
        # reproduced (golden HTML).
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
            # If the section before us was non-appendix and never closed
            # (the "swallowed" case), emit its close now — outside our div.
            if self._pending_section_close:
                self._parts.append("</div>")
                self._pending_section_close = False
        else:
            # Hold onto our close until the next section's role tells us
            # whether to flush it (sibling) or swallow it (appendix).
            self._pending_section_close = True

    # ---- Block emitters ------------------------------------------------

    def emit_kpi_row(self, block: KpiRowBlock) -> None:
        # Mid-section KPI rows: legacy did not render these; the global
        # kpi_summary above section 1 is the only KPI surface. No-op.
        return None

    def emit_paragraph(self, block: ParagraphBlock) -> None:
        if self._is_appendix:
            self._parts.append(f"<p>{block.text}</p>")
            self._appendix_emit_count += 1
        else:
            self._parts.append(f'<div class="narrative">{block.text}</div>')

    def emit_table(self, block: TableBlock, asset: Asset) -> None:
        if isinstance(asset, StatsAsset):
            html = _render_stats_table(asset.summary_stats)
            if html:
                self._parts.append(f"<h3>统计数据概览</h3>{html}")
        elif isinstance(asset, TableAsset):
            df = (
                pd.DataFrame.from_records(asset.df_records)
                if asset.df_records
                else pd.DataFrame()
            )
            html = _render_dataframe(df)
            if html:
                self._parts.append(f"<h3>数据明细</h3>{html}")

    def emit_chart(self, block: ChartBlock, asset: Asset) -> None:
        option = getattr(asset, "option", None)
        if not isinstance(option, dict):
            return
        chart_id = f"chart_{self._chart_idx}"
        self._chart_idx += 1
        chart_json = json.dumps(option, ensure_ascii=False)
        self._parts.append(
            f'<div id="{chart_id}" class="chart-container"></div>'
            f'<script>echarts.init(document.getElementById("{chart_id}"))'
            f'.setOption({chart_json});</script>'
        )

    def emit_chart_table_pair(
        self,
        block: ChartTablePairBlock,
        chart_asset: Asset,
        table_asset: Asset,
    ) -> None:
        synth_chart = ChartBlock(
            block_id=block.block_id, asset_id=block.chart_asset_id,
        )
        synth_table = TableBlock(
            block_id=block.block_id, asset_id=block.table_asset_id,
        )
        self.emit_chart(synth_chart, chart_asset)
        self.emit_table(synth_table, table_asset)

    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None:
        # Legacy doesn't produce this; render as side-by-side cards.
        if not block.columns:
            return
        cards: list[str] = []
        for col in block.columns:
            items_html = "".join(f"<li>{it}</li>" for it in col.items)
            cards.append(
                f'<div class="kpi-card" style="text-align:left;">'
                f'<div class="label">{col.title}</div>'
                f"<ul>{items_html}</ul>"
                f"</div>"
            )
        self._parts.append(f'<div class="kpi-row">{"".join(cards)}</div>')

    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None:
        if block.growth_rates:
            html = _render_growth_cards(block.growth_rates)
            if html:
                self._parts.append(f"<h3>增长率指标</h3>{html}")

    def emit_section_cover(self, block: SectionCoverBlock) -> None:
        # ``begin_section`` already emitted the heading; no extra cover.
        return None
