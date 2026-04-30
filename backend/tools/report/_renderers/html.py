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
.comparison-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 24px 0; }}
.comparison-col {{ background: white; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); overflow: hidden; transition: box-shadow 0.2s; }}
.comparison-col:hover {{ box-shadow: 0 4px 14px rgba(0,0,0,0.12); }}
.comparison-col .col-title {{ background: {primary}; color: white; padding: 10px 16px; font-weight: bold; font-size: 14px; text-align: center; }}
.comparison-col ul {{ padding: 12px 16px 16px 32px; margin: 0; line-height: 1.7; font-size: 13px; }}
.comparison-col ul li {{ margin-bottom: 6px; }}
.chart-table-pair {{ display: flex; gap: 16px; margin: 24px 0; align-items: stretch; }}
.chart-table-pair[data-layout="v"] {{ flex-direction: column; }}
.chart-table-pair[data-layout="h"] > * {{ flex: 1; min-width: 0; }}
.chart-table-pair > .chart-pane {{ flex: 1.2; }}
.chart-table-pair > .table-pane {{ flex: 1; }}
.chart-table-pair > .table-pane table {{ width: 100%; }}
.callout {{ border-left: 4px solid {neutral}; background: {bg_light}; padding: 12px 16px; margin: 16px 0; border-radius: 4px; line-height: 1.7; }}
.callout.warn {{ border-left-color: {negative}; background: #FEF1F1; }}
.callout.info {{ border-left-color: {secondary}; background: #E3F2FD; }}
.callout::before {{ display: inline-block; margin-right: 8px; font-weight: bold; }}
.callout.warn::before {{ content: "⚠️ 注意"; color: {negative}; }}
.callout.info::before {{ content: "💡 提示"; color: {secondary}; }}

/* Phase 5.4 — auto dark mode (HTML only). Other backends ignore this
   block since DOCX / PPT clients don't honour prefers-color-scheme. */
@media (prefers-color-scheme: dark) {{
    body {{ background: #1a1a1a; color: #e0e0e0; }}
    h2 {{ color: #6BA8E8; border-color: #444; }}
    h3 {{ color: #8BC34A; }}
    .meta {{ color: #999; }}
    .narrative {{ color: #d0d0d0; }}
    table.stats {{ background: #242424; }}
    table.stats th {{ background: #2a4a6e; color: #fff; }}
    table.stats td {{ color: #d0d0d0; border-bottom-color: #333; }}
    table.stats tr:nth-child(even) {{ background: #2a2a2a; }}
    .kpi-card {{ background: #2a2a2a; color: #e0e0e0; }}
    .kpi-card .label {{ color: #aaa; }}
    .kpi-card .sub {{ color: #888; }}
    .summary {{ background: #2a4a6e; }}
    .callout {{ background: #2a2a2a; color: #d0d0d0; }}
    .callout.warn {{ background: #3a1f1f; color: #ffb4b4; }}
    .callout.info {{ background: #1f2f3f; color: #b4d4f0; }}
    .comparison-col {{ background: #2a2a2a; box-shadow: 0 2px 6px rgba(0,0,0,0.4); }}
    .comparison-col:hover {{ box-shadow: 0 4px 14px rgba(0,0,0,0.6); }}
}}
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


def _render_dataframe(
    df: pd.DataFrame,
    *,
    highlight_rules: list | None = None,
    theme=None,
) -> str:
    if df is None or df.empty:
        return ""
    display = df.head(20)

    headers_list = [str(c) for c in display.columns]
    n_rows = len(display)
    cell_colors: dict[tuple[int, int], tuple[int, int, int]] = {}
    if highlight_rules and theme is not None:
        from backend.tools.report._table_highlight import (
            resolve_cell_highlights,
        )
        cell_colors = resolve_cell_highlights(
            headers_list, n_rows, highlight_rules, theme,
        )

    header = "<tr>" + "".join(f"<th>{c}</th>" for c in headers_list) + "</tr>"
    rows: list[str] = []
    for ri, (_, row) in enumerate(display.iterrows()):
        cell_chunks: list[str] = []
        for ci, v in enumerate(row):
            highlight = cell_colors.get((ri, ci))
            if highlight is not None:
                # Inline style: background + auto-contrast text colour
                lum = (
                    0.299 * highlight[0]
                    + 0.587 * highlight[1]
                    + 0.114 * highlight[2]
                )
                fg = "#FFFFFF" if lum < 140 else "#1E293B"
                bg = f"rgb({highlight[0]},{highlight[1]},{highlight[2]})"
                cell_chunks.append(
                    f'<td style="background:{bg};color:{fg};font-weight:bold;">'
                    f'{_fmt(v)}</td>'
                )
            else:
                cell_chunks.append(f"<td>{_fmt(v)}</td>")
        rows.append(f"<tr>{''.join(cell_chunks)}</tr>")
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

    def __init__(self, theme=None) -> None:  # noqa: ANN001
        super().__init__(theme=theme)
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
        # Phase 5.5 — pull all template tokens from the active theme so
        # ``HtmlBlockRenderer(theme=alt_theme)`` actually changes output.
        # Pre-Phase-5 used module-level constants; that worked only
        # because there was a single active theme.
        return HTML_TEMPLATE.format(
            title=self._title,
            author=self._author,
            date=self._date,
            content="\n".join(self._parts),
            font_cn=self._theme.font_cn,
            font_num=self._theme.font_num,
            primary=self._theme.css_primary,
            secondary=self._theme.css_secondary,
            accent=self._theme.css_accent,
            positive=self._theme.css_positive,
            negative=self._theme.css_negative,
            neutral=self._theme.css_neutral,
            bg_light=self._theme.css_bg_light,
            text_dark=self._theme.css_text_dark,
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
        # Phase 4.1 — callout styles get a coloured side bar + emoji
        # prefix injected via CSS pseudo-element.
        if block.style == "callout-warn":
            self._parts.append(f'<div class="callout warn">{block.text}</div>')
            return
        if block.style == "callout-info":
            self._parts.append(f'<div class="callout info">{block.text}</div>')
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
                self._parts.append(f"<h3>统计数据概览</h3>{html}")
        elif isinstance(asset, TableAsset):
            df = (
                pd.DataFrame.from_records(asset.df_records)
                if asset.df_records
                else pd.DataFrame()
            )
            # Phase 4.2 — apply highlight rules from the block
            html = _render_dataframe(
                df,
                highlight_rules=block.highlight_rules,
                theme=self._theme,
            )
            if html:
                heading = block.caption or "数据明细"
                self._parts.append(f"<h3>{heading}</h3>{html}")

    def emit_chart(self, block: ChartBlock, asset: Asset) -> None:
        option = getattr(asset, "option", None)
        if not isinstance(option, dict):
            return
        chart_id = f"chart_{self._chart_idx}"
        self._chart_idx += 1

        # Phase 2.5 — auto-enable axis tooltips on cartesian charts
        # (caller's option still wins via ECharts merge semantics).
        enriched = self._enrich_option_for_html(option)
        chart_json = json.dumps(enriched, ensure_ascii=False)

        self._parts.append(
            f'<div id="{chart_id}" class="chart-container" '
            f'data-chart-type="{self._detect_html_chart_type(option)}"></div>'
            f'<script>(function(){{'
            f'var c=echarts.init(document.getElementById("{chart_id}"));'
            f'c.setOption({chart_json});'
            # Auto-resize on viewport changes — matches ECharts best practice.
            f'window.addEventListener("resize",function(){{c.resize();}});'
            f'}})();</script>'
        )

    @staticmethod
    def _detect_html_chart_type(option: dict) -> str:
        """Reflect chart kind in a data-attribute so CSS can adjust
        container height per chart type if needed."""
        series = option.get("series") or []
        if not series:
            return "unknown"
        types = {(s.get("type") or "").lower() for s in series}
        if {"bar", "line"}.issubset(types):
            return "combo"
        return next(iter(types), "unknown")

    @staticmethod
    def _enrich_option_for_html(option: dict) -> dict:
        """Add HTML-only enhancements (tooltip / responsive layout / data
        labels).

        Shallow-copies the dict so we don't mutate the asset payload —
        renderers must treat ``ChartAsset.option`` as read-only since
        the same asset can be referenced by other backends in the same
        run (e.g. when LLM planner emits chart_table_pair).
        """
        import copy

        out = dict(option)
        # Preserve existing tooltip if user supplied one, else default
        # to axis-trigger which works for bar/line/combo without harm.
        if "tooltip" not in out:
            out["tooltip"] = {"trigger": "axis"}

        # Phase 4.4 — single-series BAR / horizontal-bar gets value
        # labels. Multi-series omitted to avoid clutter; matches the
        # matplotlib + pptxgenjs single-series convention.
        series = out.get("series") or []
        if (
            len(series) == 1
            and isinstance(series[0], dict)
            and (series[0].get("type") or "").lower() == "bar"
            and not series[0].get("label")
        ):
            new_series = copy.deepcopy(series)
            new_series[0]["label"] = {"show": True, "position": "top"}
            # horizontal bar (yAxis.type=category) → label position "right"
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
        """Phase 3.3 — render chart and table side-by-side via flexbox.

        Captures the children's HTML by snapshotting ``self._parts``,
        running the ``emit_chart`` / ``emit_table`` helpers, then wrapping
        the produced fragments in ``.chart-pane`` / ``.table-pane`` siblings
        inside a ``.chart-table-pair`` flex container.
        """
        # Snapshot current buffer length so we can isolate this pair's
        # nested fragments and re-pack them into wrapper divs.
        before = len(self._parts)
        synth_chart = ChartBlock(
            block_id=block.block_id, asset_id=block.chart_asset_id,
        )
        self.emit_chart(synth_chart, chart_asset)
        chart_fragments = self._parts[before:]
        del self._parts[before:]

        synth_table = TableBlock(
            block_id=block.block_id, asset_id=block.table_asset_id,
        )
        self.emit_table(synth_table, table_asset)
        table_fragments = self._parts[before:]
        del self._parts[before:]

        layout = block.layout if block.layout in ("h", "v") else "h"
        chart_html = "".join(chart_fragments)
        table_html = "".join(table_fragments) or "<p><i>(无数据)</i></p>"
        self._parts.append(
            f'<div class="chart-table-pair" data-layout="{layout}">'
            f'<div class="chart-pane">{chart_html}</div>'
            f'<div class="table-pane">{table_html}</div>'
            f'</div>'
        )

    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None:
        """Phase 3.2 — render as a CSS-grid layout with hover-elevated
        cards. Each column has a coloured title bar above a bullet list.
        ``.comparison-grid`` / ``.comparison-col`` styles live in
        ``HTML_TEMPLATE``."""
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
                self._parts.append(f"<h3>增长率指标</h3>{html}")

    def emit_section_cover(self, block: SectionCoverBlock) -> None:
        # ``begin_section`` already emitted the heading; no extra cover.
        return None
