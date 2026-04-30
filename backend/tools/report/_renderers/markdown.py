"""Markdown BlockRenderer — Step 3.

This module is the single source of truth for Markdown rendering after
the outline refactor; ``markdown_gen.py`` no longer duplicates these
helpers. Output is byte-for-byte equivalent to the previous
``_build_markdown_deterministic`` path — guarded by Step 0 baseline.
"""
from __future__ import annotations

from typing import Any

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


_MD_TEMPLATE = """# {title}

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


def _render_kpi_md(kpis: list[KPIItem]) -> str:
    if not kpis:
        return ""
    lines = ["## 核心指标\n"]
    for k in kpis:
        trend = {"positive": "↑", "negative": "↓"}.get(k.trend or "", "")
        sub = f" （{k.sub}）" if k.sub else ""
        lines.append(f"- **{k.label}**：{trend}{k.value}{sub}")
    return "\n".join(lines) + "\n"


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
    lines = [
        "| 指标 | " + " | ".join(metrics) + " |",
        "|------|" + "|".join("---" for _ in metrics) + "|",
    ]
    for col, vals in summary_stats.items():
        if not isinstance(vals, dict):
            continue
        cells = " | ".join(_fmt(vals.get(m)) for m in metrics)
        lines.append(f"| **{col}** | {cells} |")
    return "\n".join(lines)


def _render_growth_kpi(growth_rates: dict[str, dict[str, float | None]]) -> str:
    lines: list[str] = []
    for col, rates in growth_rates.items():
        if not isinstance(rates, dict):
            continue
        parts: list[str] = []
        yoy = rates.get("yoy")
        if yoy is not None:
            arrow = "↑" if yoy >= 0 else "↓"
            parts.append(f"同比: {arrow}{abs(yoy)*100:.1f}%")
        mom = rates.get("mom")
        if mom is not None:
            arrow = "↑" if mom >= 0 else "↓"
            parts.append(f"环比: {arrow}{abs(mom)*100:.1f}%")
        if parts:
            lines.append(f"- **{col}**: {', '.join(parts)}")
    return "\n".join(lines) if lines else ""


def _render_records_table(records: list[dict[str, Any]]) -> str:
    if not records:
        return "*（无数据）*"
    columns = list(records[0].keys())
    display = records[:20]
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    separator = "|" + "|".join("---" for _ in columns) + "|"
    rows = []
    for row in display:
        cells = " | ".join(_fmt(row.get(c)) for c in columns)
        rows.append(f"| {cells} |")
    extra = (
        f"\n*（仅展示前 20 行，共 {len(records)} 行）*" if len(records) > 20 else ""
    )
    return "\n".join([header, separator] + rows) + extra


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class MarkdownBlockRenderer(BlockRendererBase):
    _step_label = "Step 3"

    def __init__(self, theme=None) -> None:  # noqa: ANN001
        super().__init__(theme=theme)
        self._parts: list[str] = []
        self._title: str = ""
        self._author: str = ""
        self._date: str = ""
        self._numbered_count: int = 0  # 1-based for non-appendix sections
        self._current_role: str = "status"
        self._appendix_emit_count: int = 0

    # ---- Lifecycle -----------------------------------------------------

    def begin_document(self, outline: ReportOutline) -> None:
        self._title = outline.metadata.get("title", "")
        self._author = outline.metadata.get("author", "")
        self._date = outline.metadata.get("date", "")
        if outline.kpi_summary:
            self._parts.append(_render_kpi_md(outline.kpi_summary))

    def end_document(self) -> str:
        content = "\n".join(self._parts)
        return _MD_TEMPLATE.format(
            title=self._title,
            author=self._author,
            date=self._date,
            content=content,
        )

    def begin_section(self, section: OutlineSection, index: int) -> None:
        self._current_role = section.role
        if section.role == "appendix":
            self._parts.append(f"\n---\n\n## {section.name}\n")
            self._appendix_emit_count = 0
        else:
            self._numbered_count += 1
            self._parts.append(f"\n## {self._numbered_count}. {section.name}\n")

    def end_section(self, section: OutlineSection, index: int) -> None:
        if section.role == "appendix" and self._appendix_emit_count == 0:
            # Empty appendix → fall back to the canonical default line
            # (matches pre-refactor markdown when summary_items was empty).
            self._parts.append("\n- 以上分析基于数据，仅供参考。\n")

    # ---- Block emitters ------------------------------------------------

    def emit_kpi_row(self, block: KpiRowBlock) -> None:
        # Mid-section KPI rows are not represented in legacy markdown
        # (only the global ``kpi_summary`` appears, before section 1).
        return None

    def emit_paragraph(self, block: ParagraphBlock) -> None:
        # Phase 4.1 — callout styles render as blockquote with emoji
        # marker; gives Markdown readers a visual cue equivalent to
        # the rich-style backends' coloured boxes.
        if block.style == "callout-warn":
            self._parts.append(f"\n> ⚠️ **注意**：{block.text}\n")
            return
        if block.style == "callout-info":
            self._parts.append(f"\n> 💡 {block.text}\n")
            return

        if self._current_role == "appendix":
            self._parts.append(f"\n- {block.text}\n")
            self._appendix_emit_count += 1
        else:
            self._parts.append(f"\n{block.text}\n")

    def emit_table(self, block: TableBlock, asset: Asset) -> None:
        caption = block.caption or "数据明细"
        if isinstance(asset, StatsAsset):
            md = _render_stats_table(asset.summary_stats)
            if md:
                self._parts.append(f"\n### {caption}\n\n{md}\n")
        elif isinstance(asset, TableAsset):
            md = _render_records_table(asset.df_records)
            if md:
                self._parts.append(f"\n### {caption}\n\n{md}\n")

    def emit_chart(self, block: ChartBlock, asset: Asset) -> None:
        title = block.caption or "图表"
        self._parts.append(
            f"\n### {title}\n\n*（图表数据，可视化时需配合 ECharts 等工具渲染）*\n"
        )

    def emit_chart_table_pair(
        self,
        block: ChartTablePairBlock,
        chart_asset: Asset,
        table_asset: Asset,
    ) -> None:
        # Legacy converter never produces this; render as chart then
        # table so output is meaningful if a future planner emits it.
        chart_caption = ""
        if hasattr(chart_asset, "option"):
            title_obj = chart_asset.option.get("title", {})
            if isinstance(title_obj, dict):
                chart_caption = title_obj.get("text", "")
            elif isinstance(title_obj, str):
                chart_caption = title_obj
        synth_chart = ChartBlock(
            block_id=block.block_id,
            asset_id=block.chart_asset_id,
            caption=chart_caption or "图表",
        )
        synth_table = TableBlock(
            block_id=block.block_id,
            asset_id=block.table_asset_id,
            caption="数据明细",
        )
        self.emit_chart(synth_chart, chart_asset)
        self.emit_table(synth_table, table_asset)

    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None:
        # Legacy converter never produces this; degrade to grouped lists.
        chunks: list[str] = []
        for col in block.columns:
            chunks.append(f"\n**{col.title}**\n")
            for it in col.items:
                chunks.append(f"- {it}")
        if chunks:
            self._parts.append("\n".join(chunks) + "\n")

    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None:
        md = _render_growth_kpi(block.growth_rates)
        if md:
            self._parts.append(f"\n### 增长率指标\n\n{md}\n")

    def emit_section_cover(self, block: SectionCoverBlock) -> None:
        # Markdown has no section-cover concept; the begin_section
        # heading already serves as the visual marker.
        return None
