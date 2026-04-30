"""Chart rendering strategies — Phase 2.1 of Sprint 3 visual polish.

Single entry point for the four backend renderers (DOCX/PPT/HTML/MD)
to convert an ECharts ``option`` dict into the format each backend
needs:

  - ``render_chart_to_png(option, theme)`` → matplotlib-backed PNG
    bytes for DOCX ``add_picture``. Returns ``None`` if the chart
    type is not natively representable; caller falls back to data
    table.
  - ``echarts_to_pptxgen(option)`` → a pptxgenjs chart spec dict for
    the PptxGenJS Node bridge (re-exported from ``_pptxgen_builder``
    so all chart strategies live under one module).
  - ``echarts_to_html(option, container_id)`` → ECharts initialiser
    JS string for ``<script>`` tags.
  - ``echarts_to_data_table(option)`` → a structured representation
    every backend can lay out as a static table when no native chart
    is available (Markdown / fallback paths).

Phase 2.3 extends ``echarts_to_pptxgen`` with PIE / DOUGHNUT / combo
chart types in-place; Phase 2.2 plugs ``render_chart_to_png`` into
``DocxBlockRenderer.emit_chart``.

Font handling (matplotlib):
  * On import we register a CJK font from the host's font cache; if
    none is found, Chinese labels fall back to the default sans-serif
    (which renders boxes, not crashes). CI images should install
    ``fonts-noto-cjk``.
  * We use a non-interactive ``Agg`` backend — matplotlib import
    side-effects shouldn't touch any display server.
"""
from __future__ import annotations

import io
import logging
from typing import Any

# Pin matplotlib to the headless Agg backend BEFORE importing pyplot.
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as _fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

# Re-export the existing converter so callers find the chart strategy
# in a single module. Phase 2.3 will expand the supported chart types.
from backend.tools.report._pptxgen_builder import (
    _echarts_series_values,
    _is_waterfall,
    echarts_to_pptxgen,
)
from backend.tools.report._theme import Theme, get_theme

logger = logging.getLogger("analytica.tools.chart_renderer")


# ---------------------------------------------------------------------------
# CJK font registration
# ---------------------------------------------------------------------------

_CJK_CANDIDATES = (
    "Noto Sans CJK SC",       # Linux (fonts-noto-cjk)
    "WenQuanYi Micro Hei",    # Linux fallback
    "Source Han Sans CN",     # Adobe CJK
    "PingFang SC",            # macOS
    "Hiragino Sans GB",       # macOS
    "STHeiti",                # macOS
    "Microsoft YaHei",        # Windows
    "SimHei",                 # Windows
)


def _resolve_cjk_font() -> str | None:
    """Return the first CJK font name installed on the host, or None."""
    available = {f.name for f in _fm.fontManager.ttflist}
    for name in _CJK_CANDIDATES:
        if name in available:
            return name
    return None


_CJK_FONT = _resolve_cjk_font()
if _CJK_FONT:
    plt.rcParams["font.sans-serif"] = [_CJK_FONT, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
else:
    logger.warning(
        "No CJK font found in matplotlib font cache; chart labels with "
        "Chinese text will render as tofu boxes. Install fonts-noto-cjk "
        "or equivalent in your environment."
    )


# ---------------------------------------------------------------------------
# Chart-type detection
# ---------------------------------------------------------------------------

# Set of ECharts series.type values render_chart_to_png can handle.
_PNG_SUPPORTED = {"bar", "line", "pie"}


def _detect_chart_kind(option: dict[str, Any]) -> str | None:
    """Return one of: 'bar', 'horizontal_bar', 'line', 'pie', 'combo',
    or None if not natively representable.
    """
    series = option.get("series") or []
    if not series or _is_waterfall(series):
        return None

    types = [(s.get("type") or "").lower() for s in series]
    if len(set(types)) > 1 and {"bar", "line"}.issubset(types):
        return "combo"
    first = types[0]
    if first not in _PNG_SUPPORTED:
        return None

    if first == "bar":
        y_axis = option.get("yAxis") or {}
        if isinstance(y_axis, list):
            y_axis = y_axis[0] if y_axis else {}
        if isinstance(y_axis, dict) and y_axis.get("type") == "category":
            return "horizontal_bar"
        return "bar"
    return first  # 'line' or 'pie'


# ---------------------------------------------------------------------------
# matplotlib PNG renderer
# ---------------------------------------------------------------------------

def render_chart_to_png(
    option: dict[str, Any],
    theme: Theme | None = None,
    *,
    width_inch: float = 6.0,
    height_inch: float = 3.5,
    dpi: int = 150,
) -> bytes | None:
    """Render an ECharts option to PNG bytes via matplotlib.

    Returns ``None`` when the chart type is not in the supported set;
    caller falls back to a data table. Chart styling (palette, fonts)
    follows ``theme`` so DOCX嵌图 stays visually aligned with the rest
    of the report.

    Supported types: ``bar`` / ``horizontal_bar`` / ``line`` / ``pie``
    / ``combo`` (BAR+LINE on twin axes).
    """
    theme = theme or get_theme()
    kind = _detect_chart_kind(option)
    if kind is None:
        return None

    series = option.get("series") or []
    title = ""
    title_obj = option.get("title")
    if isinstance(title_obj, dict):
        title = title_obj.get("text", "")
    elif isinstance(title_obj, str):
        title = title_obj

    palette = ["#" + c for c in theme.chart_colors]

    fig, ax = plt.subplots(figsize=(width_inch, height_inch), dpi=dpi)
    try:
        if kind == "pie":
            _render_pie(ax, series, palette)
        elif kind == "horizontal_bar":
            _render_bar(ax, option, series, palette, horizontal=True)
        elif kind == "bar":
            _render_bar(ax, option, series, palette, horizontal=False)
        elif kind == "line":
            _render_line(ax, option, series, palette)
        elif kind == "combo":
            _render_combo(ax, option, series, palette)
        else:
            return None

        if title:
            ax.set_title(title, fontsize=14, color=theme.css_primary, pad=10)

        _style_axes(ax, theme, kind)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        return buf.getvalue()
    finally:
        plt.close(fig)


def _categories_from_axis(axis: Any) -> list[str]:
    if isinstance(axis, list):
        axis = axis[0] if axis else {}
    if isinstance(axis, dict):
        return [str(c) for c in (axis.get("data") or [])]
    return []


def _render_bar(ax, option: dict, series: list, palette: list[str],
                *, horizontal: bool) -> None:
    if horizontal:
        cats = _categories_from_axis(option.get("yAxis"))
    else:
        cats = _categories_from_axis(option.get("xAxis"))
    if not cats:
        return

    n_series = len(series)
    width = 0.8 / max(n_series, 1)

    for i, s in enumerate(series):
        values = _echarts_series_values(s.get("data") or [])
        offsets = [j + (i - (n_series - 1) / 2) * width
                   for j in range(len(cats))]
        color = palette[i % len(palette)]
        label = s.get("name") or ""
        if horizontal:
            ax.barh(offsets, values, height=width, color=color, label=label)
            if n_series == 1:
                for j, v in enumerate(values):
                    ax.text(v, j, f" {v:,.1f}", va="center",
                            fontsize=9, color="#1E293B")
        else:
            ax.bar(offsets, values, width=width, color=color, label=label)
            if n_series == 1:
                for j, v in enumerate(values):
                    ax.text(j, v, f"{v:,.1f}", ha="center", va="bottom",
                            fontsize=9, color="#1E293B")

    if horizontal:
        ax.set_yticks(range(len(cats)))
        ax.set_yticklabels(cats)
        ax.invert_yaxis()
    else:
        ax.set_xticks(range(len(cats)))
        ax.set_xticklabels(cats, rotation=0)

    if n_series > 1:
        ax.legend(loc="best", fontsize=9, frameon=False)


def _render_line(ax, option: dict, series: list, palette: list[str]) -> None:
    cats = _categories_from_axis(option.get("xAxis"))
    if not cats:
        return
    x = list(range(len(cats)))
    for i, s in enumerate(series):
        values = _echarts_series_values(s.get("data") or [])
        ax.plot(x, values, color=palette[i % len(palette)],
                label=s.get("name") or "", linewidth=2, marker="o",
                markersize=4)
    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    if len(series) > 1:
        ax.legend(loc="best", fontsize=9, frameon=False)


def _render_pie(ax, series: list, palette: list[str]) -> None:
    """ECharts pie series: ``data: [{name, value}, ...]``."""
    if not series:
        return
    raw = series[0].get("data") or []
    labels: list[str] = []
    values: list[float] = []
    for item in raw:
        if isinstance(item, dict):
            labels.append(str(item.get("name", "")))
            try:
                values.append(float(item.get("value") or 0))
            except (TypeError, ValueError):
                values.append(0.0)
    if not values or sum(values) <= 0:
        return
    colors = [palette[i % len(palette)] for i in range(len(values))]
    ax.pie(
        values, labels=labels, colors=colors,
        autopct="%1.1f%%", pctdistance=0.75,
        startangle=90, textprops={"fontsize": 10},
    )
    ax.axis("equal")


def _render_combo(ax, option: dict, series: list, palette: list[str]) -> None:
    """BAR + LINE on twin axes (line shares categories with bar)."""
    cats = _categories_from_axis(option.get("xAxis"))
    if not cats:
        return
    x = list(range(len(cats)))

    bar_series = [s for s in series if (s.get("type") or "").lower() == "bar"]
    line_series = [s for s in series if (s.get("type") or "").lower() == "line"]

    width = 0.8 / max(len(bar_series), 1)
    for i, s in enumerate(bar_series):
        values = _echarts_series_values(s.get("data") or [])
        offsets = [j + (i - (len(bar_series) - 1) / 2) * width for j in x]
        ax.bar(offsets, values, width=width,
               color=palette[i % len(palette)],
               label=s.get("name") or "", alpha=0.85)

    if line_series:
        ax2 = ax.twinx()
        for i, s in enumerate(line_series):
            values = _echarts_series_values(s.get("data") or [])
            ax2.plot(x, values,
                     color=palette[(i + len(bar_series)) % len(palette)],
                     label=s.get("name") or "",
                     linewidth=2, marker="s", markersize=4)
        ax2.tick_params(axis="y", labelsize=9)
        ax2.spines["top"].set_visible(False)

    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    # Combine both legends if line was drawn
    handles, labels = ax.get_legend_handles_labels()
    if line_series:
        h2, l2 = ax2.get_legend_handles_labels()  # noqa: F821 — bound above
        handles += h2
        labels += l2
    if handles:
        ax.legend(handles, labels, loc="best", fontsize=9, frameon=False)


def _style_axes(ax, theme: Theme, kind: str) -> None:
    if kind == "pie":
        return
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#E2E8F0")
    ax.spines["bottom"].set_color("#E2E8F0")
    ax.tick_params(axis="both", colors="#64748B", labelsize=9)
    ax.grid(axis="y" if kind in {"bar", "line", "combo"} else "x",
            color="#E2E8F0", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------------------
# HTML / data-table strategies
# ---------------------------------------------------------------------------

def echarts_to_html(option: dict[str, Any], container_id: str) -> str:
    """Inline ECharts initialiser for a ``<div id="container_id">``.

    Used by HtmlBlockRenderer; kept here so all chart strategies live
    under one module for Phase 2.4's capability-matrix audit.
    """
    import json
    payload = json.dumps(option, ensure_ascii=False)
    return (
        f'<div id="{container_id}" class="chart-container"></div>'
        f'<script>echarts.init(document.getElementById("{container_id}"))'
        f'.setOption({payload});</script>'
    )


def echarts_to_data_table(option: dict[str, Any]) -> dict[str, Any] | None:
    """Extract chart data into a backend-agnostic table representation.

    Returns ``{"title": str, "headers": list[str], "rows": list[list]}``
    or ``None`` when the option carries no usable series data.

    Each backend renders the table in its native idiom (HTML <table>,
    DOCX add_table, PPT addTable, Markdown pipe table). Used as the
    universal fallback when ``render_chart_to_png`` /
    ``echarts_to_pptxgen`` return ``None``.
    """
    series = option.get("series") or []
    if not series:
        return None

    title = ""
    title_obj = option.get("title")
    if isinstance(title_obj, dict):
        title = title_obj.get("text", "")
    elif isinstance(title_obj, str):
        title = title_obj

    # Detect pie shape (data is [{name, value}, ...])
    first = series[0]
    raw = first.get("data") or []
    if first.get("type") == "pie" or (
        raw and isinstance(raw[0], dict) and "name" in raw[0]
    ):
        rows = [
            [str(item.get("name", "")), item.get("value")]
            for item in raw if isinstance(item, dict)
        ]
        return {
            "title": title,
            "headers": ["类别", series[0].get("name") or "数值"],
            "rows": rows,
        }

    # Cartesian: pull categories from x or y axis
    cats = _categories_from_axis(option.get("xAxis"))
    if not cats:
        cats = _categories_from_axis(option.get("yAxis"))
    if not cats:
        return None

    headers: list[str] = ["类别"] + [
        s.get("name") or f"系列{i+1}" for i, s in enumerate(series)
    ]
    rows: list[list[Any]] = []
    series_values = [_echarts_series_values(s.get("data") or []) for s in series]
    for j, cat in enumerate(cats):
        row: list[Any] = [str(cat)]
        for vals in series_values:
            row.append(vals[j] if j < len(vals) else None)
        rows.append(row)

    return {"title": title, "headers": headers, "rows": rows}


__all__ = [
    "render_chart_to_png",
    "echarts_to_pptxgen",  # re-export
    "echarts_to_html",
    "echarts_to_data_table",
    "_detect_chart_kind",
    "_PNG_SUPPORTED",
    "_CJK_FONT",
]
